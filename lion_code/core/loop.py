"""Pure Pi-compatible provider/tool agent loop."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from inspect import isawaitable

from lion_code.core.events import (
    AgentEndEvent,
    AgentEvent,
    AgentStartEvent,
    MessageEndEvent,
    MessageStartEvent,
    MessageUpdateEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    ToolExecutionUpdateEvent,
    TurnEndEvent,
    TurnStartEvent,
)
from lion_code.core.messages import (
    AgentMessage,
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
)
from lion_code.core.provider import CancellationToken, ModelProvider
from lion_code.core.provider_events import (
    AssistantDoneEvent,
    AssistantErrorEvent,
    AssistantMessageEvent,
    AssistantStartEvent,
)
from lion_code.core.tools import AgentTool, AgentToolResult

BeforeToolCall = Callable[[ToolCall], Awaitable[tuple[bool, str | None]]]
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
    signal: CancellationToken | None = None,
    get_steering_messages: Callable[[], Sequence[AgentMessage]] | None = None,
    get_follow_up_messages: Callable[[], Sequence[AgentMessage]] | None = None,
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
                error = _error_message(model, f"Agent stopped after max_turns={max_turns}")
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
            # cache-heat, summarization, memory injection) without rebuilding.
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
                assistant = _error_message(model, "Provider produced no assistant message")
                yield MessageStartEvent(message=assistant)
                yield MessageEndEvent(message=assistant)

            messages.append(assistant)
            new_messages.append(assistant)
            if assistant.stop_reason in {"error", "aborted"}:
                yield TurnEndEvent(message=assistant)
                yield AgentEndEvent(messages=new_messages)
                return

            tool_results: list[ToolResultMessage] = []
            calls = list(assistant.tool_calls)
            has_more_tools = bool(calls)
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
                event_batches = await _run_parallel_tool_batch(
                    call_batch,
                    tool_by_name,
                    signal,
                    before_tool_call,
                    after_tool_call,
                )
                for events in event_batches:
                    for event in events:
                        yield event
                        if isinstance(event, MessageEndEvent) and isinstance(
                            event.message, ToolResultMessage
                        ):
                            tool_results.append(event.message)
                            messages.append(event.message)
                            new_messages.append(event.message)

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
    signal: CancellationToken | None,
    before_tool_call: BeforeToolCall | None,
    after_tool_call: AfterToolCall | None,
) -> list[list[AgentEvent]]:
    """Run a parallel batch and return its event streams in call order."""
    results = await asyncio.gather(
        *(
            _collect_tool_events(
                call,
                tools,
                signal,
                before_tool_call,
                after_tool_call,
            )
            for call in calls
        ),
        return_exceptions=True,
    )
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return results


async def _collect_tool_events(
    call: ToolCall,
    tools: Mapping[str, AgentTool],
    signal: CancellationToken | None,
    before_tool_call: BeforeToolCall | None,
    after_tool_call: AfterToolCall | None,
) -> list[AgentEvent]:
    """Collect one parallel tool's events without duplicating its start event."""
    return [
        event
        async for event in _execute_tool_call(
            call,
            tools,
            signal,
            before_tool_call,
            after_tool_call,
            include_start=False,
        )
    ]


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
    signal: CancellationToken | None,
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
    signal: CancellationToken | None,
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

    blocked = False
    block_reason: str | None = None
    if before_tool_call is not None:
        blocked, block_reason = await before_tool_call(call)

    if blocked:
        result = _error_result(block_reason or "Tool execution was blocked")
        is_error = True
    elif signal is not None and signal.is_cancelled():
        result = _error_result("Operation aborted")
        is_error = True
    else:
        tool = tools.get(call.name)
        if tool is None:
            result = _error_result(f"Tool {call.name} not found")
            is_error = True
        else:
            result, is_error, updates = await _run_tool(tool, call, signal)
            for update in updates:
                yield ToolExecutionUpdateEvent(
                    tool_call_id=call.id,
                    tool_name=call.name,
                    args=call.arguments,
                    partial_result=update,
                )

    if after_tool_call is not None:
        result, is_error = await after_tool_call(call, result, is_error)

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


async def _run_tool(
    tool: AgentTool,
    call: ToolCall,
    signal: CancellationToken | None,
) -> tuple[AgentToolResult, bool, list[AgentToolResult]]:
    updates: list[AgentToolResult] = []
    accepting = True

    def on_update(partial: AgentToolResult) -> None:
        if accepting:
            updates.append(partial.model_copy(deep=True))

    try:
        result = await tool.execute(call.id, call.arguments, signal, on_update)
        # Honor structured errors returned without raising: the host runtime
        # surfaces permission denials, hook rejections, and freshness failures
        # as ``AgentToolResult(is_error=True)`` rather than exceptions.
        return result, result.is_error, updates
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - tools are an isolation boundary
        return _error_result(str(exc)), True, updates
    finally:
        accepting = False


def _error_result(message: str) -> AgentToolResult:
    return AgentToolResult(content=[TextContent(text=message)], details={}, is_error=True)


def _error_message(model: str, message: str) -> AssistantMessage:
    return AssistantMessage(
        model=model,
        content=[],
        stop_reason="error",
        error_message=message,
    )
