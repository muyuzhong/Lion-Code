"""Translate Tau's transitional provider parser output into Pi stream events."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any, Protocol

import httpx

from lion_code.core.cancellation import CancellationView
from lion_code.core.messages import (
    AssistantMessage,
    AssistantMessageDiagnostic,
    TextContent,
    ThinkingContent,
    Usage,
)

from ._provider_events import (
    ProviderErrorEvent,
    ProviderEvent,
    ProviderResponseEndEvent,
    ProviderResponseStartEvent,
    ProviderRetryEvent,
    ProviderTextDeltaEvent,
    ProviderThinkingDeltaEvent,
    ProviderToolCallEvent,
)
from .events import (
    AssistantDoneEvent,
    AssistantErrorEvent,
    AssistantMessageEvent,
    AssistantStartEvent,
    TextDeltaEvent,
    TextEndEvent,
    TextStartEvent,
    ThinkingDeltaEvent,
    ThinkingEndEvent,
    ThinkingStartEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from .http_errors import provider_http_error_message
from .retry import provider_retry_event, retry_delay_seconds, wait_for_retry


def _snapshot(message: AssistantMessage) -> AssistantMessage:
    return message.model_copy(deep=True)


async def _end_active_block(
    partial: AssistantMessage,
    index: int | None,
) -> AsyncIterator[AssistantMessageEvent]:
    """End the active text/thinking block before the provider changes channels."""
    if index is None:
        return
    block = partial.content[index]
    if isinstance(block, TextContent):
        yield TextEndEvent(
            content_index=index,
            content=block.text,
            partial=_snapshot(partial),
        )
    elif isinstance(block, ThinkingContent):
        yield ThinkingEndEvent(
            content_index=index,
            content=block.thinking,
            partial=_snapshot(partial),
        )


def _copy_replay_metadata(target: AssistantMessage, source: AssistantMessage) -> None:
    """Copy provider metadata onto streamed blocks without changing their order."""
    source_thinking = [block for block in source.content if isinstance(block, ThinkingContent)]
    target_thinking = [block for block in target.content if isinstance(block, ThinkingContent)]
    for target_block, source_block in zip(target_thinking, source_thinking, strict=False):
        target_block.thinking_signature = source_block.thinking_signature
        target_block.redacted = source_block.redacted

    source_text = [block for block in source.content if isinstance(block, TextContent)]
    target_text = [block for block in target.content if isinstance(block, TextContent)]
    for target_text_block, source_text_block in zip(target_text, source_text, strict=False):
        target_text_block.text_signature = source_text_block.text_signature


def _finish_reason(value: str | None, *, has_tools: bool) -> str:
    if has_tools or value in {"tool_calls", "tool_use", "toolUse"}:
        return "toolUse"
    if value in {"length", "max_tokens", "MAX_TOKENS", "incomplete"}:
        return "length"
    return "stop"


async def canonicalize_provider_stream(
    source: AsyncIterator[ProviderEvent],
    *,
    api: str,
    provider: str,
    model: str,
    signal: CancellationView | None = None,
) -> AsyncIterator[AssistantMessageEvent]:
    """Canonicalize one old internal parser stream.

    Provider parsers remain isolated behind this private bridge while they are
    migrated incrementally. The public provider protocol exposes only Pi events.
    """
    partial = AssistantMessage(api=api, provider=provider, model=model)
    active_index: int | None = None
    active_kind: str | None = None
    started = False
    terminal = False

    async for event in source:
        if isinstance(event, ProviderRetryEvent):
            # Retries are provider-internal at the Pi AI boundary.
            continue
        if isinstance(event, ProviderResponseStartEvent):
            if not started:
                started = True
                yield AssistantStartEvent(partial=_snapshot(partial))
            continue
        if not started:
            started = True
            yield AssistantStartEvent(partial=_snapshot(partial))

        if isinstance(event, ProviderTextDeltaEvent):
            if active_kind != "text":
                async for end_event in _end_active_block(partial, active_index):
                    yield end_event
                active_index = len(partial.content)
                active_kind = "text"
                partial.content.append(TextContent(text=""))
                yield TextStartEvent(content_index=active_index, partial=_snapshot(partial))
            assert active_index is not None
            block = partial.content[active_index]
            assert isinstance(block, TextContent)
            block.text += event.delta
            yield TextDeltaEvent(
                content_index=active_index,
                delta=event.delta,
                partial=_snapshot(partial),
            )
        elif isinstance(event, ProviderThinkingDeltaEvent):
            if active_kind != "thinking":
                async for end_event in _end_active_block(partial, active_index):
                    yield end_event
                active_index = len(partial.content)
                active_kind = "thinking"
                partial.content.append(ThinkingContent(thinking=""))
                yield ThinkingStartEvent(
                    content_index=active_index,
                    partial=_snapshot(partial),
                )
            assert active_index is not None
            block = partial.content[active_index]
            assert isinstance(block, ThinkingContent)
            block.thinking += event.delta
            yield ThinkingDeltaEvent(
                content_index=active_index,
                delta=event.delta,
                partial=_snapshot(partial),
            )
        elif isinstance(event, ProviderToolCallEvent):
            async for end_event in _end_active_block(partial, active_index):
                yield end_event
            active_index = None
            active_kind = None
            index = len(partial.content)
            partial.content.append(event.tool_call.model_copy(deep=True))
            yield ToolCallStartEvent(content_index=index, partial=_snapshot(partial))
            yield ToolCallEndEvent(
                content_index=index,
                tool_call=event.tool_call,
                partial=_snapshot(partial),
            )
        elif isinstance(event, ProviderResponseEndEvent):
            async for end_event in _end_active_block(partial, active_index):
                yield end_event
            active_index = None
            active_kind = None

            # Preserve the exact streamed content order. The parser's final
            # message remains authoritative only for response metadata/usage.
            final = event.message.model_copy(deep=True)
            final.api = api
            final.provider = provider
            final.model = model
            final.content = [block.model_copy(deep=True) for block in partial.content]
            if not final.content and event.message.content:
                final.content = [block.model_copy(deep=True) for block in event.message.content]
            _copy_replay_metadata(final, event.message)
            final.stop_reason = _finish_reason(
                event.finish_reason,
                has_tools=bool(final.tool_calls),
            )  # type: ignore[assignment]
            yield AssistantDoneEvent(reason=final.stop_reason, message=final)  # type: ignore[arg-type]
            terminal = True
        elif isinstance(event, ProviderErrorEvent):
            error = partial.model_copy(deep=True)
            error.stop_reason = "error"
            error.error_message = event.message
            error.diagnostics = [
                AssistantMessageDiagnostic(type="provider_error", details=event.data)
            ]
            yield AssistantErrorEvent(reason="error", error=error)
            terminal = True

    if not started:
        yield AssistantStartEvent(partial=_snapshot(partial))
    if not terminal:
        error = partial.model_copy(deep=True)
        if signal is not None and signal.is_cancelled():
            error.stop_reason = "aborted"
            error.usage = Usage()
            yield AssistantErrorEvent(reason="aborted", error=error)
            return
        error.stop_reason = "error"
        error.error_message = "Provider stream ended without a terminal event"
        error.usage = Usage()
        yield AssistantErrorEvent(reason="error", error=error)


def parse_sse_line(line: str) -> str | None:
    """Return the ``data:`` payload of an SSE line, or ``None`` otherwise."""
    if not line.startswith("data:"):
        return None
    return line.removeprefix("data:").strip()

def int_or_none(value: object) -> int | None:
    """Return an int (excluding bool) or ``None``."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def is_transient_status(status_code: int) -> bool:
    """Return whether an HTTP status is worth a provider retry."""
    return status_code in {408, 409, 425, 429} or status_code >= 500


def tool_build_finalize(
    builders: Mapping[int, Any],
) -> list[Any]:
    """Finalize ordered tool builders into ``ToolCall`` objects."""
    return [builder.build(index) for index, builder in sorted(builders.items())]


class ProviderStreamParser(Protocol):
    """Per-endpoint SSE handler driven by the shared streaming envelope."""

    # True once any model output (text/thinking/tool args) has been emitted;
    # the envelope uses it to decide whether a mid-stream drop is retryable.
    emitted_content: bool
    # True when the parser already emitted a terminal error event and the
    # envelope must not call finalize().
    fatal: bool

    def feed(self, event: str) -> tuple[list[ProviderEvent], bool]:
        """Consume one SSE ``data:`` payload, returning (events, should_stop)."""
        ...

    def finalize(self) -> list[ProviderEvent]:
        """Return the trailing tool-call and response-end events."""
        ...


async def stream_provider_post(
    *,
    client: httpx.AsyncClient,
    url: str,
    payload: Mapping[str, Any],
    headers: Mapping[str, str],
    signal: CancellationView | None,
    max_retries: int,
    max_retry_delay_seconds: float,
    provider_name: str,
    model: str,
    parser_factory: Callable[[], ProviderStreamParser],
) -> AsyncIterator[ProviderEvent]:
    """Run the shared streaming POST + retry envelope for a given endpoint.

    The per-endpoint differences (SSE chunk handling and final-message
    assembly) live in the ``ProviderStreamParser`` produced by
    ``parser_factory``; everything else — HTTP, status/network retries,
    cancellation, and the opening ``response_start`` event — is shared.
    """
    attempt = 0
    while True:
        parser = parser_factory()
        try:
            async with client.stream(
                "POST", url, json=payload, headers=headers
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    body_text = body.decode(errors="replace")
                    if (
                        attempt < max_retries
                        and is_transient_status(response.status_code)
                    ):
                        delay = retry_delay_seconds(
                            attempt,
                            max_delay_seconds=max_retry_delay_seconds,
                        )
                        yield provider_retry_event(
                            attempt=attempt,
                            max_retries=max_retries,
                            delay_seconds=delay,
                            reason=f"HTTP {response.status_code}",
                            data={
                                "status_code": response.status_code,
                                "body": body_text,
                            },
                        )
                        attempt += 1
                        if not await wait_for_retry(delay, signal=signal):
                            return
                        continue
                    yield ProviderErrorEvent(
                        message=provider_http_error_message(
                            provider_name=provider_name,
                            status_code=response.status_code,
                            body=body_text,
                            model=model,
                        ),
                        data={
                            "status_code": response.status_code,
                            "body": body_text,
                            "attempts": attempt + 1,
                        },
                    )
                    return

                yield ProviderResponseStartEvent(model=model)
                async for line in response.aiter_lines():
                    if signal is not None and signal.is_cancelled():
                        return
                    event = parse_sse_line(line)
                    if event is None:
                        continue
                    events, stop = parser.feed(event)
                    for parser_event in events:
                        yield parser_event
                    if stop:
                        break
                if not parser.fatal:
                    for parser_event in parser.finalize():
                        yield parser_event
                return
        except httpx.HTTPError as exc:
            if not parser.emitted_content and attempt < max_retries:
                delay = retry_delay_seconds(
                    attempt,
                    max_delay_seconds=max_retry_delay_seconds,
                )
                yield provider_retry_event(
                    attempt=attempt,
                    max_retries=max_retries,
                    delay_seconds=delay,
                    reason="network error",
                    data={
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                    },
                )
                attempt += 1
                if not await wait_for_retry(delay, signal=signal):
                    return
                continue
            yield ProviderErrorEvent(
                message=str(exc),
                data={"attempts": attempt + 1},
            )
            return
