"""Pure Pi-compatible provider/tool agent loop."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from inspect import isawaitable

from lion_code.core.cancellation import CancellationView
from lion_code.core.events import (
    AgentEndEvent,
    AgentEvent,
    AgentStartEvent,
    CancelledEvent,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    ToolExecutionUpdateEvent,
    TurnEndEvent,
    TurnFailedEvent,
    TurnStartEvent,
)
from lion_code.core.messages import (
    AgentMessage,
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
)
from lion_code.core.provider import ModelProvider
from lion_code.core.provider_events import (
    AssistantDoneEvent,
    AssistantErrorEvent,
    AssistantMessageEvent,
    AssistantStartEvent,
)
from lion_code.core.tools import AgentTool, AgentToolResult

BeforeToolCall = Callable[[ToolCall], Awaitable[tuple[bool, str | None]]]
BeforeToolCalls = Callable[
    [AssistantMessage],
    Awaitable[str | None] | str | None,
]
AfterToolCall = Callable[
    [ToolCall, AgentToolResult, bool],
    Awaitable[tuple[AgentToolResult, bool]],
]
GetTools = Callable[[], Sequence[AgentTool]]
GetSystem = Callable[[], str]
PrepareContext = Callable[
    [list[AgentMessage]],
    Awaitable[list[AgentMessage]] | list[AgentMessage],
]


@dataclass(frozen=True, slots=True)
class _ToolRunOutcome:
    result: AgentToolResult
    is_error: bool


# stop_reason 到收尾事件的映射：error 发 TurnFailedEvent，aborted 发 CancelledEvent。
_TERMINAL_EVENT_TYPES: dict[str, type[TurnFailedEvent] | type[CancelledEvent]] = {
    "error": TurnFailedEvent,
    "aborted": CancelledEvent,
}


async def run_agent_loop(
    *,
    provider: ModelProvider,
    model: str,
    system: str,
    get_system: GetSystem | None = None,
    messages: list[AgentMessage],
    tools: list[AgentTool],
    get_tools: GetTools | None = None,
    prepare_context: PrepareContext | None = None,
    prompts: Sequence[AgentMessage] = (),
    max_turns: int | None = None,
    signal: CancellationView | None = None,
    get_steering_messages: Callable[[], Sequence[AgentMessage]] | None = None,
    get_follow_up_messages: Callable[[], Sequence[AgentMessage]] | None = None,
    before_tool_calls: BeforeToolCalls | None = None,
    before_tool_call: BeforeToolCall | None = None,
    after_tool_call: AfterToolCall | None = None,
) -> AsyncIterator[AgentEvent]:
    """Run the provider/tool loop and emit Pi-compatible agent events."""
    new_messages = list(prompts)
    if prompts:
        messages.extend(prompts)

    yield AgentStartEvent()
    yield TurnStartEvent()
    for prompt in prompts:
        yield MessageStartEvent(message=prompt)
        yield MessageEndEvent(message=prompt)

    if max_turns is not None and max_turns < 1:
        error = _error_message(model, "max_turns must be at least 1")
        messages.append(error)
        new_messages.append(error)
        yield MessageStartEvent(message=error)
        yield MessageEndEvent(message=error)
        yield TurnEndEvent(message=error)
        yield AgentEndEvent(messages=new_messages)
        return

    turn = 1
    first_turn = True
    pending = tuple(get_steering_messages() if get_steering_messages else ())

    while True:
        has_more_tools = True
        while has_more_tools or pending:
            if not first_turn:
                yield TurnStartEvent()
            first_turn = False

            for message in pending:
                messages.append(message)
                new_messages.append(message)
                yield MessageStartEvent(message=message)
                yield MessageEndEvent(message=message)
            pending = ()

            if max_turns is not None and turn > max_turns:
                error = _error_message(
                    model, f"Agent stopped after max_turns={max_turns}"
                )
                messages.append(error)
                new_messages.append(error)
                yield MessageStartEvent(message=error)
                yield MessageEndEvent(message=error)
                yield TurnEndEvent(message=error)
                yield AgentEndEvent(messages=new_messages)
                return

            # Resolve tools per turn so dynamically discovered, lazily activated,
            # skill-added, and per-subagent tool views are honored.
            active_tools = list(get_tools() if get_tools else tools)
            tool_by_name = {tool.name: tool for tool in active_tools}
            # Resolve the system prompt per turn so plan-mode, dynamic skills,
            # and tool-activation prompt updates are visible without rebuilding.
            current_system = get_system() if get_system else system
            # Let the host shape provider context (trim tool results, budget,
            # cache-heat, and summarization) without rebuilding.
            provider_messages = _provider_context(messages)
            if prepare_context is not None:
                prepared = prepare_context(provider_messages)
                provider_messages = (
                    await prepared if isawaitable(prepared) else prepared
                )
            # Python async generators cannot pass a yielding callback through a
            # normal await cleanly, so consume the assistant sub-generator and
            # retain its final message through the terminal event.
            assistant = None
            async for event in _assistant_events(
                provider=provider,
                model=model,
                system=current_system,
                messages=provider_messages,
                tools=active_tools,
                signal=signal,
            ):
                yield event
                if isinstance(event, MessageEndEvent) and isinstance(
                    event.message, AssistantMessage
                ):
                    assistant = event.message

            if assistant is None:  # defensive: _assistant_events always terminates
                assistant = _error_message(
                    model, "Provider produced no assistant message"
                )
                yield MessageStartEvent(message=assistant)
                yield MessageEndEvent(message=assistant)

            messages.append(assistant)
            new_messages.append(assistant)
            if assistant.stop_reason in {"error", "aborted"}:
                yield _TERMINAL_EVENT_TYPES[assistant.stop_reason](message=assistant)
                yield TurnEndEvent(message=assistant)
                yield AgentEndEvent(messages=new_messages)
                return

            tool_results: list[ToolResultMessage] = []
            calls = list(assistant.tool_calls)
            has_more_tools = bool(calls)
            if calls and before_tool_calls is not None:
                decision = before_tool_calls(assistant)
                stop_reason = await decision if isawaitable(decision) else decision
                if stop_reason:
                    for call in calls:
                        message = ToolResultMessage(
                            tool_call_id=call.id,
                            tool_name=call.name,
                            content=[
                                TextContent(
                                    text=f"Tool call not executed: {stop_reason}"
                                )
                            ],
                            is_error=True,
                        )
                        tool_results.append(message)
                        messages.append(message)
                        new_messages.append(message)
                        yield MessageStartEvent(message=message)
                        yield MessageEndEvent(message=message)
                    yield TurnEndEvent(message=assistant, tool_results=tool_results)
                    yield AgentEndEvent(messages=new_messages)
                    return
            terminate_flags: list[bool] = []
            for call_batch in _tool_call_batches(calls, tool_by_name):
                if len(call_batch) == 1:
                    async for event in _execute_tool_call(
                        call_batch[0],
                        tool_by_name,
                        signal,
                        before_tool_call,
                        after_tool_call,
                    ):
                        yield event
                        if isinstance(event, ToolExecutionEndEvent):
                            terminate_flags.append(event.result.terminate is True)
                        if isinstance(event, MessageEndEvent) and isinstance(
                            event.message, ToolResultMessage
                        ):
                            tool_results.append(event.message)
                            messages.append(event.message)
                            new_messages.append(event.message)
                    continue

                for call in call_batch:
                    yield ToolExecutionStartEvent(
                        tool_call_id=call.id,
                        tool_name=call.name,
                        args=call.arguments,
                    )
                async for event in _run_parallel_tool_batch(
                    call_batch,
                    tool_by_name,
                    signal,
                    before_tool_call,
                    after_tool_call,
                ):
                    yield event
                    if isinstance(event, ToolExecutionEndEvent):
                        terminate_flags.append(event.result.terminate is True)
                    if isinstance(event, MessageEndEvent) and isinstance(
                        event.message, ToolResultMessage
                    ):
                        tool_results.append(event.message)
                        messages.append(event.message)
                        new_messages.append(event.message)

            has_more_tools = bool(calls) and not (
                len(terminate_flags) == len(calls) and all(terminate_flags)
            )

            yield TurnEndEvent(message=assistant, tool_results=tool_results)
            turn += 1
            pending = tuple(get_steering_messages() if get_steering_messages else ())

        follow_ups = tuple(get_follow_up_messages() if get_follow_up_messages else ())
        if follow_ups:
            pending = follow_ups
            continue
        break

    yield AgentEndEvent(messages=new_messages)


def _tool_call_batches(
    calls: Sequence[ToolCall],
    tools: Mapping[str, AgentTool],
) -> list[list[ToolCall]]:
    """Group adjacent parallel calls while keeping sequential tools as barriers."""
    batches: list[list[ToolCall]] = []
    parallel_batch: list[ToolCall] = []
    for call in calls:
        tool = tools.get(call.name)
        if tool is not None and tool.execution_mode == "parallel":
            parallel_batch.append(call)
            continue
        if parallel_batch:
            batches.append(parallel_batch)
            parallel_batch = []
        batches.append([call])
    if parallel_batch:
        batches.append(parallel_batch)
    return batches


async def _run_parallel_tool_batch(
    calls: Sequence[ToolCall],
    tools: Mapping[str, AgentTool],
    signal: CancellationView | None,
    before_tool_call: BeforeToolCall | None,
    after_tool_call: AfterToolCall | None,
) -> AsyncIterator[AgentEvent]:
    """实时转发并行工具事件，并按调用顺序提交最终消息。"""
    queue: asyncio.Queue[tuple[int, AgentEvent | None, BaseException | None]] = (
        asyncio.Queue()
    )
    message_events: list[list[AgentEvent]] = [[] for _ in calls]

    async def forward(index: int, call: ToolCall) -> None:
        try:
            async for event in _execute_tool_call(
                call,
                tools,
                signal,
                before_tool_call,
                after_tool_call,
                include_start=False,
            ):
                await queue.put((index, event, None))
        except BaseException as exc:
            await queue.put((index, None, exc))
        else:
            await queue.put((index, None, None))

    tasks = [
        asyncio.create_task(forward(index, call)) for index, call in enumerate(calls)
    ]
    remaining = len(tasks)
    try:
        while remaining:
            index, event, error = await queue.get()
            if error is not None:
                raise error
            if event is None:
                remaining -= 1
                continue
            if isinstance(event, (MessageStartEvent, MessageEndEvent)):
                message_events[index].append(event)
            else:
                yield event

        for events in message_events:
            for event in events:
                yield event
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _provider_context(messages: list[AgentMessage]) -> list[AgentMessage]:
    """Return replayable messages while retaining failures in durable history.

    Providers cannot consistently accept an assistant turn with no content. Lion
    persists terminal failures for diagnostics, but an empty failed or aborted
    turn is not model context and must not poison the next request.
    """
    return [
        message
        for message in messages
        if not (
            isinstance(message, AssistantMessage)
            and message.stop_reason in {"error", "aborted"}
            and not message.content
        )
    ]


async def _assistant_events(
    *,
    provider: ModelProvider,
    model: str,
    system: str,
    messages: list[AgentMessage],
    tools: list[AgentTool],
    signal: CancellationView | None,
) -> AsyncIterator[AgentEvent]:
    source: AsyncIterator[AssistantMessageEvent] = provider.stream_response(
        model=model,
        system=system,
        messages=messages,
        tools=tools,
        signal=signal,
    )
    started = False
    async for event in source:
        if isinstance(event, AssistantStartEvent):
            started = True
            yield MessageStartEvent(message=event.partial)
        elif isinstance(event, AssistantDoneEvent):
            message = event.message.model_copy(update={"stop_reason": event.reason})
            if not started:
                yield MessageStartEvent(message=message)
            yield MessageEndEvent(message=message)
        elif isinstance(event, AssistantErrorEvent):
            message = event.error.model_copy(update={"stop_reason": event.reason})
            if not started:
                yield MessageStartEvent(message=message)
            yield MessageEndEvent(message=message)
        else:
            yield MessageUpdateEvent(
                message=event.partial,
                assistant_message_event=event,
            )


async def _execute_tool_call(
    call: ToolCall,
    tools: Mapping[str, AgentTool],
    signal: CancellationView | None,
    before_tool_call: BeforeToolCall | None,
    after_tool_call: AfterToolCall | None,
    *,
    include_start: bool = True,
) -> AsyncIterator[AgentEvent]:
    if include_start:
        yield ToolExecutionStartEvent(
            tool_call_id=call.id,
            tool_name=call.name,
            args=call.arguments,
        )

    tool = tools.get(call.name)
    prepared_call = call
    if tool is None:
        result = _error_result(f"Tool {call.name} not found")
        is_error = True
    else:
        try:
            prepared_call = _prepare_tool_call(tool, call)
        except Exception as exc:  # noqa: BLE001 - 参数兼容钩子属于工具边界
            result = _error_result(str(exc))
            is_error = True
        else:
            blocked = False
            block_reason: str | None = None
            if before_tool_call is not None:
                blocked, block_reason = await before_tool_call(prepared_call)

            if blocked:
                result = _error_result(block_reason or "Tool execution was blocked")
                is_error = True
            elif signal is not None and signal.is_cancelled():
                result = _error_result("Operation aborted")
                is_error = True
            else:
                outcome: _ToolRunOutcome | None = None
                async for item in _run_tool(tool, prepared_call, signal):
                    if isinstance(item, _ToolRunOutcome):
                        outcome = item
                        continue
                    update = item
                    yield ToolExecutionUpdateEvent(
                        tool_call_id=call.id,
                        tool_name=call.name,
                        args=call.arguments,
                        partial_result=update,
                    )
                if outcome is None:  # pragma: no cover - 私有生成器始终产生终态
                    outcome = _ToolRunOutcome(
                        result=_error_result("Tool produced no result"),
                        is_error=True,
                    )
                result = outcome.result
                is_error = outcome.is_error

    if after_tool_call is not None:
        result, is_error = await after_tool_call(prepared_call, result, is_error)

    yield ToolExecutionEndEvent(
        tool_call_id=call.id,
        tool_name=call.name,
        result=result,
        is_error=is_error,
    )
    message = ToolResultMessage(
        tool_call_id=call.id,
        tool_name=call.name,
        content=result.content,
        details=result.details,
        added_tool_names=result.added_tool_names,
        is_error=is_error,
    )
    yield MessageStartEvent(message=message)
    yield MessageEndEvent(message=message)


def _prepare_tool_call(tool: AgentTool, call: ToolCall) -> ToolCall:
    if tool.prepare_arguments is None:
        return call
    prepared = tool.prepare_arguments(call.arguments)
    if not isinstance(prepared, Mapping):
        raise TypeError(f"Tool {tool.name} prepare_arguments must return a mapping")
    if prepared is call.arguments:
        return call
    return call.model_copy(update={"arguments": dict(prepared)})


async def _run_tool(
    tool: AgentTool,
    call: ToolCall,
    signal: CancellationView | None,
) -> AsyncIterator[AgentToolResult | _ToolRunOutcome]:
    updates: asyncio.Queue[AgentToolResult] = asyncio.Queue()
    accepting = True

    def on_update(partial: AgentToolResult) -> None:
        if accepting:
            updates.put_nowait(partial.model_copy(deep=True))

    task = asyncio.create_task(tool.execute(call.id, call.arguments, signal, on_update))
    try:
        while not task.done():
            next_update = asyncio.create_task(updates.get())
            done, _ = await asyncio.wait(
                {task, next_update},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if next_update in done:
                yield next_update.result()
            else:
                next_update.cancel()
                with suppress(asyncio.CancelledError):
                    await next_update

        while not updates.empty():
            yield updates.get_nowait()

        try:
            result = task.result()
            yield _ToolRunOutcome(result=result, is_error=result.is_error)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - tools are an isolation boundary
            yield _ToolRunOutcome(result=_error_result(str(exc)), is_error=True)
    finally:
        accepting = False
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


def _error_result(message: str) -> AgentToolResult:
    return AgentToolResult(
        content=[TextContent(text=message)], details={}, is_error=True
    )


def _error_message(model: str, message: str) -> AssistantMessage:
    return AssistantMessage(
        model=model,
        content=[],
        stop_reason="error",
        error_message=message,
    )
