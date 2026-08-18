"""Anthropic Messages API provider."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping

import httpx

from lion_code.core.cancellation import CancellationView
from lion_code.core.messages import (
    AgentMessage,
    AssistantMessage,
    TextContent,
    ThinkingContent,
    ToolResultMessage,
    Usage,
    UserMessage,
    assistant_content,
    message_to_user,
)
from lion_code.core.tools import AgentTool, ToolCall
from lion_code.core.types import JSONValue

from ._provider_events import (
    ProviderErrorEvent,
    ProviderEvent,
    ProviderResponseEndEvent,
    ProviderTextDeltaEvent,
    ProviderThinkingDeltaEvent,
    ProviderToolCallEvent,
)
from .config import AnthropicConfig
from .events import AssistantMessageEvent
from .http import create_async_client, loads_object
from .stream import (
    canonicalize_provider_stream,
    int_or_none,
    stream_provider_post,
    tool_build_finalize,
)

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4096


class AnthropicProvider:
    """Provider adapter for Anthropic's streaming Messages API."""

    def __init__(
        self,
        config: AnthropicConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config
        self._client = client
        self._owns_client = client is None

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this provider created it."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def stream_response(
        self,
        *,
        model: str,
        system: str,
        messages: list[AgentMessage],
        tools: list[AgentTool],
        signal: CancellationView | None = None,
    ) -> AsyncIterator[AssistantMessageEvent]:
        """Stream one response as Pi-compatible assistant message events."""
        raw = self._stream_provider_events(
            model=model, system=system, messages=messages, tools=tools, signal=signal
        )
        return canonicalize_provider_stream(
            raw,
            api="anthropic-messages",
            provider="anthropic",
            model=model,
            signal=signal,
        )

    def _stream_provider_events(
        self,
        *,
        model: str,
        system: str,
        messages: list[AgentMessage],
        tools: list[AgentTool],
        signal: CancellationView | None = None,
    ) -> AsyncIterator[ProviderEvent]:
        """Stream one Anthropic response as provider-neutral events."""

        async def iterator() -> AsyncIterator[ProviderEvent]:
            client = self._get_client()
            api_key = self._config.api_key
            base_url = self._config.base_url
            payload = _build_messages_payload(
                model=model,
                system=system,
                messages=messages,
                tools=tools,
                max_tokens=self._config.max_tokens,
                thinking_budget_tokens=self._config.thinking_budget_tokens,
                thinking_effort=self._config.thinking_effort,
                thinking_mode=self._config.thinking_mode,
            )
            headers = {
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
                **(dict(self._config.headers or {})),
                "x-api-key": api_key,
            }
            url = f"{base_url.rstrip('/')}/messages"

            async for event in stream_provider_post(
                client=client,
                url=url,
                payload=payload,
                headers=headers,
                signal=signal,
                max_retries=self._config.max_retries,
                max_retry_delay_seconds=self._config.max_retry_delay_seconds,
                provider_name=self._config.provider_name,
                model=model,
                parser_factory=_AnthropicStreamParser,
            ):
                yield event

        return iterator()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = create_async_client(timeout=self._config.timeout_seconds)
        return self._client


class _AnthropicStreamParser:
    """Parser for Anthropic Messages API SSE chunks."""

    def __init__(self) -> None:
        self.emitted_content = False
        self.fatal = False
        self._content_parts: list[str] = []
        self._thinking_parts: list[str] = []
        self._thinking_signature: str | None = None
        self._tool_builders: dict[int, _AnthropicToolBuilder] = {}
        self._finish_reason: str | None = None
        self._usage: Usage | None = None

    def feed(self, event: str) -> tuple[list[ProviderEvent], bool]:
        chunk = loads_object(event)
        if chunk is None:
            self.fatal = True
            return [ProviderErrorEvent(message="Provider returned invalid JSON chunk")], True

        events: list[ProviderEvent] = []
        event_type = chunk.get("type")
        if event_type == "message_start":
            message = chunk.get("message")
            if isinstance(message, Mapping):
                self._usage = _usage_from_message_start(message.get("usage"))
        elif event_type == "content_block_start":
            block = chunk.get("content_block")
            if isinstance(block, Mapping) and block.get("type") == "tool_use":
                index = int(chunk.get("index", 0))
                builder = self._tool_builders.setdefault(index, _AnthropicToolBuilder())
                builder.id = _string_or_empty(block.get("id"))
                builder.name = _string_or_empty(block.get("name"))
                self.emitted_content = True
        elif event_type == "content_block_delta":
            delta = chunk.get("delta")
            if isinstance(delta, Mapping):
                delta_type = delta.get("type")
                if delta_type == "text_delta":
                    text = _string_or_empty(delta.get("text"))
                    if text:
                        self.emitted_content = True
                        self._content_parts.append(text)
                        events.append(ProviderTextDeltaEvent(delta=text))
                elif delta_type == "thinking_delta":
                    thinking = _string_or_empty(delta.get("thinking"))
                    if thinking:
                        self.emitted_content = True
                        self._thinking_parts.append(thinking)
                        events.append(ProviderThinkingDeltaEvent(delta=thinking))
                elif delta_type == "signature_delta":
                    signature = _string_or_empty(delta.get("signature"))
                    if signature:
                        self._thinking_signature = (
                            f"{self._thinking_signature or ''}{signature}"
                        )
                elif delta_type == "input_json_delta":
                    index = int(chunk.get("index", 0))
                    builder = self._tool_builders.setdefault(index, _AnthropicToolBuilder())
                    builder.arguments_parts.append(
                        _string_or_empty(delta.get("partial_json"))
                    )
                    self.emitted_content = True
        elif event_type == "message_delta":
            delta = chunk.get("delta")
            if isinstance(delta, Mapping):
                self._finish_reason = (
                    _string_or_empty(delta.get("stop_reason")) or self._finish_reason
                )
            self._usage = _apply_message_delta_usage(self._usage, chunk.get("usage"))
        elif event_type == "error":
            error = chunk.get("error")
            message = "Provider returned an error"
            if isinstance(error, Mapping):
                message = _string_or_empty(error.get("message")) or message
            self.fatal = True
            return [ProviderErrorEvent(message=message, data=chunk)], True
        elif event_type == "message_stop":
            return events, True
        return events, False

    def finalize(self) -> list[ProviderEvent]:
        tool_calls = tool_build_finalize(self._tool_builders)
        events: list[ProviderEvent] = [
            ProviderToolCallEvent(tool_call=tool_call) for tool_call in tool_calls
        ]
        content = assistant_content("".join(self._content_parts), tool_calls)
        if self._thinking_parts:
            content.insert(
                0,
                ThinkingContent(
                    thinking="".join(self._thinking_parts),
                    thinking_signature=self._thinking_signature,
                ),
            )
        events.append(
            ProviderResponseEndEvent(
                message=AssistantMessage(
                    content=content,
                    usage=self._usage or Usage(),
                ),
                finish_reason=self._finish_reason,
            )
        )
        return events


class _AnthropicToolBuilder:
    def __init__(self) -> None:
        self.id = ""
        self.name = ""
        self.arguments_parts: list[str] = []

    def build(self, index: int) -> ToolCall:
        arguments_text = "".join(self.arguments_parts)
        arguments = loads_object(arguments_text) if arguments_text else {}
        if arguments is None:
            arguments = {"_raw_arguments": arguments_text}
        return ToolCall(
            id=self.id or f"tool-call-{index}",
            name=self.name,
            arguments=arguments,
        )


def _build_messages_payload(
    *,
    model: str,
    system: str,
    messages: list[AgentMessage],
    tools: list[AgentTool],
    max_tokens: int | None = None,
    thinking_budget_tokens: int | None = None,
    thinking_effort: str | None = None,
    thinking_mode: str = "budget",
) -> dict[str, JSONValue]:
    resolved_max_tokens = max_tokens or DEFAULT_MAX_TOKENS
    if thinking_budget_tokens is not None:
        resolved_max_tokens = max(resolved_max_tokens, thinking_budget_tokens + 1024)
    payload: dict[str, JSONValue] = {
        "model": model,
        "max_tokens": resolved_max_tokens,
        "stream": True,
        "system": system,
        "messages": [_anthropic_message(message) for message in messages],
    }
    if thinking_mode == "disabled":
        payload["thinking"] = {"type": "disabled"}
    elif thinking_mode == "adaptive" and thinking_effort is not None:
        payload["thinking"] = {"type": "adaptive", "display": "summarized"}
        payload["output_config"] = {"effort": thinking_effort}
    elif thinking_budget_tokens is not None:
        payload["thinking"] = {
            "type": "enabled",
            "budget_tokens": thinking_budget_tokens,
        }
    if tools:
        payload["tools"] = [_anthropic_tool(tool) for tool in tools]
    return payload


def _anthropic_message(message: AgentMessage) -> dict[str, JSONValue]:
    if isinstance(message, UserMessage):
        return {"role": "user", "content": message.text}
    if isinstance(message, AssistantMessage):
        content: list[JSONValue] = []
        for block in message.content:
            if isinstance(block, TextContent):
                content.append({"type": "text", "text": block.text})
            elif isinstance(block, ThinkingContent):
                thinking: dict[str, JSONValue] = {
                    "type": "thinking",
                    "thinking": block.thinking,
                }
                if block.thinking_signature is not None:
                    thinking["signature"] = block.thinking_signature
                content.append(thinking)
            elif isinstance(block, ToolCall):
                content.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.arguments,
                    }
                )
        return {"role": "assistant", "content": content}
    if isinstance(message, ToolResultMessage):
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": message.tool_call_id,
                    "content": message.text,
                    "is_error": bool(message.is_error),
                }
            ],
        }
    return _anthropic_message(message_to_user(message))


def _anthropic_tool(tool: AgentTool) -> dict[str, JSONValue]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": dict(tool.input_schema),
    }


def _string_or_empty(value: object) -> str:
    return value if isinstance(value, str) else ""


def _usage_from_message_start(raw: object) -> Usage:
    """Build a Usage from the ``message_start`` event's ``message.usage``.

    Ports Pi's anthropic-messages.ts message_start handling. Cost is left unset
    (None) because Tau has no per-model pricing table.
    """
    data = raw if isinstance(raw, Mapping) else {}
    cache_creation = data.get("cache_creation")
    cache_write_1h = (
        int_or_none(cache_creation.get("ephemeral_1h_input_tokens"))
        if isinstance(cache_creation, Mapping)
        else None
    )
    usage = Usage(
        input=int_or_none(data.get("input_tokens")) or 0,
        output=int_or_none(data.get("output_tokens")) or 0,
        cache_read=int_or_none(data.get("cache_read_input_tokens")) or 0,
        cache_write=int_or_none(data.get("cache_creation_input_tokens")) or 0,
        cache_write_1h=cache_write_1h,
    )
    usage.total_tokens = usage.input + usage.output + usage.cache_read + usage.cache_write
    return usage


def _apply_message_delta_usage(usage: Usage | None, raw: object) -> Usage | None:
    """Apply the ``message_delta`` event's ``usage`` onto the running Usage.

    Ports Pi's anthropic-messages.ts message_delta handling: only overwrite
    fields the provider reports (non-null), then recompute the token total.
    """
    if not isinstance(raw, Mapping):
        return usage
    usage = usage or Usage()
    if (value := int_or_none(raw.get("input_tokens"))) is not None:
        usage.input = value
    if (value := int_or_none(raw.get("output_tokens"))) is not None:
        usage.output = value
    if (value := int_or_none(raw.get("cache_read_input_tokens"))) is not None:
        usage.cache_read = value
    if (value := int_or_none(raw.get("cache_creation_input_tokens"))) is not None:
        usage.cache_write = value
    details = raw.get("output_tokens_details")
    if isinstance(details, Mapping):
        thinking = int_or_none(details.get("thinking_tokens"))
        if thinking is not None:
            usage.reasoning = thinking
    usage.total_tokens = usage.input + usage.output + usage.cache_read + usage.cache_write
    return usage
