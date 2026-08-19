"""会话内对话运行时：AgentHarness、canonical 活跃消息与 live Provider/model 的唯一 Owner。

ConversationRuntime 不做编排决策：不触发压缩、不写 Session、不感知 ProviderController。
它只拥有"当前这段对话"的全部活跃状态，并把 steer/follow-up/cancel 等会话内命令
桥接到 Kernel Harness。
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Sequence
from typing import Any

from ..adapters import adapt_active_tools
from ..core import (
    AgentHarness,
    AgentHarnessConfig,
    AgentMessage,
    EventListener,
    QueueSnapshot,
)
from ..core.cancellation import CancellationView
from ..core.events import AgentEvent, MessageEndEvent, MessageUpdateEvent
from ..core.loop import BeforeToolCalls, PrepareContext
from ..core.messages import AssistantMessage, UserMessage, message_text
from ..core.provider import ModelProvider
from ..core.provider_events import TextDeltaEvent
from ..tooling import ToolRuntime

# 通用 Harness 的绝对迭代保险上限，与用户预算解耦：预算的 max_turns 只经
# UsageLedger 在 Core 工具边界生效（见 AgentRuntime.before_core_tool_calls），
# 这里仅防止无工具调用的纯文本死循环（usage-ownership.md §1 禁止把预算值传给 Harness）。
ITERATION_SAFETY_CAP = 200


class ConversationRuntime:
    """拥有 AgentHarness、活跃消息与 live Provider/model 的对话运行时。"""

    def __init__(
        self,
        *,
        provider: ModelProvider,
        model: str,
        get_system: Callable[[], str],
        tool_runtime: ToolRuntime,
        cancellation: CancellationView | None = None,
        cancel_callback: Callable[[], None] | None = None,
        prepare_context: PrepareContext | None = None,
        before_tool_calls: BeforeToolCalls | None = None,
    ) -> None:
        self._provider = provider
        self._tool_runtime = tool_runtime
        self._cancel_callback = cancel_callback
        self._output_buffer: list[str] | None = None
        self._captured_assistant_text: str | None = None
        self._retired_provider_tasks: set[asyncio.Task[object]] = set()
        self._background_errors: list[BaseException] = []
        self.harness = AgentHarness(
            AgentHarnessConfig(
                provider=provider,
                model=model,
                system=get_system(),
                get_system=get_system,
                tools=[],
                get_tools=lambda: adapt_active_tools(self._tool_runtime),
                prepare_context=prepare_context,
                max_turns=ITERATION_SAFETY_CAP,
                before_tool_calls=before_tool_calls,
            ),
            cancellation=cancellation,
        )

    # ─── live Provider / model 命令（ProviderController 消费的窄端口）───

    def bind_before_tool_calls(self, hook: BeforeToolCalls | None) -> None:
        """AgentRuntime 构造完成后注入工具调用前的预算闸门钩子。"""
        self.harness.config.before_tool_calls = hook

    def set_model(self, model: str) -> None:
        """更新后续 Provider 请求使用的模型。"""
        self.harness.config.model = model

    def replace_provider(self, provider: ModelProvider) -> ModelProvider:
        """热替换后续 Provider 请求使用的 provider，返回旧 provider。

        Harness 每轮 live 读取 ``config.provider``，故直接改 live 配置即生效。
        旧 provider 的关闭由调用方经 ``retire_provider`` 排程。
        """
        previous = self._provider
        self._provider = provider
        self.harness.config.provider = provider
        return previous

    def retire_provider(self, provider: ModelProvider) -> None:
        """排程一个已替换 Provider 的异步关闭；下个状态边界收敛异常。"""

        close = getattr(provider, "aclose", None)
        if close is None:
            return

        async def close_provider() -> object:
            await close()
            return None

        self._schedule_background_operation(close_provider)

    @property
    def is_running(self) -> bool:
        return self.harness.is_running

    @property
    def provider(self) -> ModelProvider:
        """返回摘要与模型限制发现所复用的 live Provider。"""
        return self._provider

    @property
    def model(self) -> str:
        """返回后续 Provider 请求使用的 live model。"""
        return self.harness.config.model

    # ─── 事件流与订阅 ─────────────────────────────────────────

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        """注册一个同步或异步的 Agent 事件监听器，返回取消订阅回调。"""
        return self.harness.subscribe(listener)

    async def emit(self, event: AgentEvent) -> None:
        """通过 Harness 的同一订阅流发布运行时事件。"""
        await self.harness.emit(event)

    # ─── 对话推进 ─────────────────────────────────────────────

    async def prompt(self, content: str) -> None:
        """驱动一次完整对话：消费完 harness 产生的全部事件。"""
        async for _ in self.harness.prompt(content):
            pass

    async def continue_(self) -> None:
        """使用当前 Harness 上下文继续运行，不追加新的用户消息。"""
        async for _ in self.harness.continue_():
            pass

    async def replace_active_context(self, messages: Sequence[AgentMessage]) -> None:
        """替换模型活跃上下文；durable history 仍由 SessionRecorder 保留。"""
        self.harness.clear_queues()
        self.harness.replace_messages(messages)

    async def reset_active_context(self, content: str) -> None:
        """只替换模型活跃上下文；durable history 由 SessionRecorder 保留。"""
        await self.replace_active_context([UserMessage(content=content)])

    def steer(self, content: str) -> QueueSnapshot:
        """将新的用户消息加入流中操作队列。"""
        self.harness.steer(content)
        return self.queue_snapshot()

    def follow_up(self, content: str) -> QueueSnapshot:
        """将新的用户消息加入本轮后续队列。"""
        self.harness.follow_up(content)
        return self.queue_snapshot()

    def queue_snapshot(self) -> QueueSnapshot:
        """返回只包含文本的队列快照，不泄漏 Harness 类型。"""
        queued = self.harness.queued_messages
        return QueueSnapshot(
            steering=tuple(message_text(message) for message in queued.steering),
            follow_up=tuple(message_text(message) for message in queued.follow_up),
        )

    def cancel(self) -> None:
        """请求取消当前正在进行的模型流。"""
        if self._cancel_callback is not None:
            self._cancel_callback()
            return
        self.harness.cancel()

    @property
    def cancelled(self) -> bool:
        """返回运行协调器的取消视图。"""
        return self.harness._cancellation.is_cancelled()

    @property
    def messages(self) -> tuple[AgentMessage, ...]:
        """返回当前对话的消息快照。"""
        return self.harness.messages

    def last_assistant(self) -> AssistantMessage | None:
        return next(
            (
                message
                for message in reversed(self.messages)
                if isinstance(message, AssistantMessage)
            ),
            None,
        )

    # ─── 当前 run 的文本捕获 ──────────────────────────────────

    def begin_run_capture(self) -> None:
        """开始捕获本次 run 的助手文本增量与最终消息。"""
        self._output_buffer = []
        self._captured_assistant_text = None

    def end_run_capture(self) -> str:
        """结束捕获并返回本次 run 的文本（增量优先，最终消息兜底）。"""
        text = "".join(self._output_buffer or [])
        if not text:
            text = self._captured_assistant_text or ""
        self._output_buffer = None
        self._captured_assistant_text = None
        return text

    async def capture_event(self, event: AgentEvent) -> None:
        """run 捕获监听器：只在本 run 捕获开启时记录文本，不参与渲染。"""
        if self._output_buffer is None:
            return
        if isinstance(event, MessageUpdateEvent) and isinstance(
            event.assistant_message_event, TextDeltaEvent
        ):
            self._output_buffer.append(event.assistant_message_event.delta)
        elif isinstance(event, MessageEndEvent) and isinstance(
            event.message, AssistantMessage
        ):
            self._captured_assistant_text = event.message.text

    # ─── 后台清理任务（retired provider 关闭）─────────────────

    def _schedule_background_operation(
        self,
        operation: Callable[[], Coroutine[Any, Any, object]],
    ) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(operation())
            return
        task: asyncio.Task[object] = loop.create_task(operation())
        self._retired_provider_tasks.add(task)

        def collect_result(done: asyncio.Task[object]) -> None:
            self._retired_provider_tasks.discard(done)
            try:
                done.result()
            except BaseException as error:
                self._background_errors.append(error)

        task.add_done_callback(collect_result)

    async def flush_background_operations(self) -> None:
        """收敛已排程的 Provider 关闭任务，重放第一个异常。"""
        pending = tuple(self._retired_provider_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if self._background_errors:
            raise self._background_errors.pop(0)

    async def aclose(self) -> None:
        """关闭由当前 live Provider 持有的连接资源。"""
        close = getattr(self._provider, "aclose", None)
        if close is not None:
            await close()
