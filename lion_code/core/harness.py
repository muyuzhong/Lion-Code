"""Stateful reusable agent harness built on the Pi-compatible loop."""

from __future__ import annotations

from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from inspect import isawaitable

from lion_code.core.cancellation import CancellationToken, CancellationView
from lion_code.core.events import (
    AgentEvent,
    AgentStartEvent,
    MessageEndEvent,
    MessageStartEvent,
)
from lion_code.core.loop import (
    BeforeToolCalls,
    GetSystem,
    GetTools,
    PrepareContext,
    run_agent_loop,
)
from lion_code.core.messages import (
    AgentMessage,
    AssistantMessage,
    TextContent,
    ToolResultMessage,
    UserMessage,
)
from lion_code.core.provider import ModelProvider
from lion_code.core.tools import AgentTool

EventListener = Callable[[AgentEvent], Awaitable[None] | None]


@dataclass(frozen=True, slots=True)
class QueuedMessages:
    steering: tuple[AgentMessage, ...] = ()
    follow_up: tuple[AgentMessage, ...] = ()


@dataclass(slots=True)
class AgentHarnessConfig:
    provider: ModelProvider
    model: str
    system: str
    get_system: GetSystem | None = None
    tools: list[AgentTool] = field(default_factory=list)
    get_tools: GetTools | None = None
    prepare_context: PrepareContext | None = None
    max_turns: int | None = None
    before_tool_calls: BeforeToolCalls | None = None


class AgentHarness:
    """Reusable stateful agent brain independent of coding/UI policy."""

    def __init__(
        self,
        config: AgentHarnessConfig,
        *,
        messages: Sequence[AgentMessage] = (),
        cancellation: CancellationView | None = None,
    ) -> None:
        self._config = config
        self._messages = list(messages)
        self._listeners: list[EventListener] = []
        if cancellation is None:
            self._owned_cancellation: CancellationToken | None = CancellationToken()
            self._cancellation: CancellationView = self._owned_cancellation
        else:
            self._owned_cancellation = None
            self._cancellation = cancellation
        self._running = False
        self._steering_queue: deque[AgentMessage] = deque()
        self._follow_up_queue: deque[AgentMessage] = deque()

    @property
    def messages(self) -> tuple[AgentMessage, ...]:
        return tuple(self._messages)

    @property
    def config(self) -> AgentHarnessConfig:
        return self._config

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def queued_messages(self) -> QueuedMessages:
        return QueuedMessages(tuple(self._steering_queue), tuple(self._follow_up_queue))

    def append_message(self, message: AgentMessage) -> None:
        self._messages.append(message)

    def replace_messages(self, messages: Sequence[AgentMessage]) -> None:
        self._messages = list(messages)

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            with suppress(ValueError):
                self._listeners.remove(listener)

        return unsubscribe

    async def emit(self, event: AgentEvent) -> None:
        """向当前实例的订阅者发布一个 Kernel 事件。"""

        await self._notify(event)

    def cancel(self) -> None:
        if self._owned_cancellation is not None:
            self._owned_cancellation.cancel()

    def steer(self, content: str) -> QueuedMessages:
        return self.steer_message(UserMessage(content=content))

    def steer_message(self, message: AgentMessage) -> QueuedMessages:
        self._steering_queue.append(message)
        return self.queued_messages

    def follow_up(self, content: str) -> QueuedMessages:
        return self.follow_up_message(UserMessage(content=content))

    def follow_up_message(self, message: AgentMessage) -> QueuedMessages:
        self._follow_up_queue.append(message)
        return self.queued_messages

    def clear_queues(self) -> QueuedMessages:
        snapshot = self.queued_messages
        self._steering_queue.clear()
        self._follow_up_queue.clear()
        return snapshot

    def prompt_message(self, message: AgentMessage) -> AsyncIterator[AgentEvent]:
        self._ensure_not_running()
        if self._owned_cancellation is not None:
            self._owned_cancellation.reset()
        self._running = True
        return self._run(prompts=(message,))

    def prompt(self, content: str) -> AsyncIterator[AgentEvent]:
        return self.prompt_message(UserMessage(content=content))

    def continue_(self) -> AsyncIterator[AgentEvent]:
        self._ensure_not_running()
        if self._owned_cancellation is not None:
            self._owned_cancellation.reset()
        self._running = True
        return self._run()

    async def _run(
        self,
        *,
        prompts: Sequence[AgentMessage] = (),
    ) -> AsyncIterator[AgentEvent]:
        signal = self._cancellation
        try:
            repaired_before_run = self._append_interrupted_tool_results()
            async for event in run_agent_loop(
                provider=self._config.provider,
                model=self._config.model,
                system=self._config.system,
                get_system=self._config.get_system,
                messages=self._messages,
                prompts=prompts,
                tools=self._config.tools,
                get_tools=self._config.get_tools,
                prepare_context=self._config.prepare_context,
                max_turns=self._config.max_turns,
                signal=signal,
                get_steering_messages=self._drain_steering_messages,
                get_follow_up_messages=self._drain_follow_up_messages,
                before_tool_calls=self._config.before_tool_calls,
            ):
                await self._notify(event)
                yield event
                if isinstance(event, AgentStartEvent):
                    # 保持 AgentStart 为首个事件，再把恢复出的未配对调用交给持久化监听器。
                    for message in repaired_before_run:
                        for repair_event in (
                            MessageStartEvent(message=message),
                            MessageEndEvent(message=message),
                        ):
                            await self._notify(repair_event)
                            yield repair_event
        finally:
            repaired: tuple[ToolResultMessage, ...] = ()
            if signal.is_cancelled():
                repaired = self._append_interrupted_tool_results()
            self._running = False
            # finally 中无法再向已结束的生成器 yield，但订阅者仍必须看到修复消息。
            for message in repaired:
                await self._notify(MessageStartEvent(message=message))
                await self._notify(MessageEndEvent(message=message))

    async def _notify(self, event: AgentEvent) -> None:
        for listener in list(self._listeners):
            result = listener(event)
            if isawaitable(result):
                await result

    def _ensure_not_running(self) -> None:
        if self._running:
            raise RuntimeError(
                "AgentHarness is already running; use steer() or follow_up() to queue messages."
            )

    def _drain_steering_messages(self) -> tuple[AgentMessage, ...]:
        return self._drain_queue(self._steering_queue)

    def _drain_follow_up_messages(self) -> tuple[AgentMessage, ...]:
        return self._drain_queue(self._follow_up_queue)

    def _drain_queue(self, queue: deque[AgentMessage]) -> tuple[AgentMessage, ...]:
        if not queue:
            return ()
        return (queue.popleft(),)

    def _append_interrupted_tool_results(self) -> tuple[ToolResultMessage, ...]:
        returned_ids = {
            message.tool_call_id
            for message in self._messages
            if isinstance(message, ToolResultMessage)
        }
        repaired: list[ToolResultMessage] = []
        for message in tuple(self._messages):
            if not isinstance(message, AssistantMessage):
                continue
            for call in message.tool_calls:
                if call.id in returned_ids:
                    continue
                returned_ids.add(call.id)
                result = ToolResultMessage(
                    tool_call_id=call.id,
                    tool_name=call.name,
                    content=[TextContent(text="Tool call interrupted by user")],
                    is_error=True,
                )
                self._messages.append(result)
                repaired.append(result)
        return tuple(repaired)
