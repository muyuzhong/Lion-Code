"""OpenAI-compatible chat completions provider."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from json import dumps
from typing import Any, Protocol

import httpx

from lion_code.core.cancellation import CancellationView
from lion_code.core.messages import (
    AgentMessage,
    AssistantMessage,
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
from .config import OpenAICompatibleConfig
from .events import AssistantMessageEvent
from .http import create_async_client, loads_object
from .stream import (
    ProviderStreamParser,
    canonicalize_provider_stream,
    int_or_none,
    stream_provider_post,
    tool_build_finalize,
)


class OpenAICompatibleProvider:
    """Provider adapter for OpenAI-compatible `/chat/completions` APIs."""

    def __init__(
        self,
        config: OpenAICompatibleConfig,
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
        raw = self._stream_chat_completions(
            model=model, system=system, messages=messages, tools=tools, signal=signal
        )
        return canonicalize_provider_stream(
            raw,
            api=self._config.api,
            provider=getattr(self._config, "provider_name", "openai-compatible"),
            model=model,
            signal=signal,
        )

    def _stream_chat_completions(
        self,
        *,
        model: str,
        system: str,
        messages: list[AgentMessage],
        tools: list[AgentTool],
        signal: CancellationView | None = None,
    ) -> AsyncIterator[ProviderEvent]:
        """Stream one chat completion response as provider-neutral events."""
        payload = _build_chat_payload(
            model=model,
            system=system,
            messages=messages,
            tools=tools,
            reasoning_effort=self._config.reasoning_effort,
            max_tokens=self._config.max_tokens,
        )
        return self._stream(
            model=model,
            url=f"{self._config.base_url.rstrip('/')}/chat/completions",
            payload=payload,
            parser_factory=_ChatStreamParser,
            signal=signal,
        )

    def _stream(
        self,
        *,
        model: str,
        url: str,
        payload: Mapping[str, JSONValue],
        parser_factory: Callable[[], ProviderStreamParser],
        signal: CancellationView | None = None,
    ) -> AsyncIterator[ProviderEvent]:
        """Run the shared streaming POST + retry envelope for a given endpoint.

        The per-endpoint differences (SSE chunk handling and final-message
        assembly) live in the ``ProviderStreamParser`` produced by ``parser_factory``;
        everything else — HTTP, status/network retries, cancellation, and the
        opening ``response_start`` event — lives in ``stream_provider_post``.
        """

        async def iterator() -> AsyncIterator[ProviderEvent]:
            client = self._get_client()
            api_key = self._config.api_key
            request_url = url
            headers = dict(self._config.headers or {})
            has_authorization = any(key.casefold() == "authorization" for key in headers)
            if not has_authorization:
                headers["Authorization"] = f"Bearer {api_key}"

            async for event in stream_provider_post(
                client=client,
                url=request_url,
                payload=payload,
                headers=headers,
                signal=signal,
                max_retries=self._config.max_retries,
                max_retry_delay_seconds=self._config.max_retry_delay_seconds,
                provider_name=self._config.provider_name,
                model=model,
                parser_factory=parser_factory,
            ):
                yield event

        return iterator()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = create_async_client(timeout=self._config.timeout_seconds)
        return self._client


class _ChatStreamParser:
    """Parser for OpenAI `/chat/completions` SSE chunks."""

    def __init__(self) -> None:
        self.emitted_content = False
        self.fatal = False
        self._content_parts: list[str] = []
        self._thinking_parts: list[str] = []
        self._thinking_signature: str | None = None
        self._tool_call_builders: dict[int, _ToolCallBuilder] = {}
        self._finish_reason: str | None = None
        self._usage: Usage | None = None

    def feed(self, event: str) -> tuple[list[ProviderEvent], bool]:
        if event == "[DONE]":
            return [], True

        chunk = loads_object(event)
        if chunk is None:
            self.fatal = True
            return [ProviderErrorEvent(message="Provider returned invalid JSON chunk")], True

        # The final usage chunk (from stream_options) carries usage at the top
        # level and often has empty choices.
        chunk_usage = chunk.get("usage")
        if isinstance(chunk_usage, Mapping):
            self._usage = _parse_chunk_usage(chunk_usage)

        choice = _first_choice(chunk)
        if choice is None:
            return [], False

        # Fallback: some providers (e.g. Moonshot) attach usage to the choice
        # instead of the chunk. Matches Pi's per-chunk `!chunk.usage` guard: the
        # fallback applies whenever this chunk lacks top-level usage.
        choice_usage = choice.get("usage")
        if not isinstance(chunk_usage, Mapping) and isinstance(choice_usage, Mapping):
            self._usage = _parse_chunk_usage(choice_usage)

        self._finish_reason = choice.get("finish_reason") or self._finish_reason
        delta = choice.get("delta")
        if not isinstance(delta, Mapping):
            return [], False

        events: list[ProviderEvent] = []
        content = delta.get("content")
        if isinstance(content, str) and content:
            self.emitted_content = True
            self._content_parts.append(content)
            events.append(ProviderTextDeltaEvent(delta=content))

        thinking = _thinking_delta(delta)
        if thinking is not None:
            field_name, text = thinking
            self.emitted_content = True
            self._thinking_parts.append(text)
            self._thinking_signature = self._thinking_signature or field_name
            events.append(ProviderThinkingDeltaEvent(delta=text))

        for tool_call_delta in _tool_call_deltas(delta):
            self.emitted_content = True
            index = int(tool_call_delta.get("index", 0))
            builder = self._tool_call_builders.setdefault(index, _ToolCallBuilder())
            builder.add_delta(tool_call_delta)

        return events, False

    def finalize(self) -> list[ProviderEvent]:
        tool_calls = tool_build_finalize(self._tool_call_builders)
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


class _ToolCallBuilder:
    def __init__(self) -> None:
        self.id = ""
        self.name = ""
        self.arguments_parts: list[str] = []

    def add_delta(self, delta: Mapping[str, Any]) -> None:
        call_id = delta.get("id")
        if isinstance(call_id, str):
            self.id = call_id

        function = delta.get("function")
        if not isinstance(function, Mapping):
            return

        name = function.get("name")
        if isinstance(name, str):
            self.name = name

        arguments = function.get("arguments")
        if isinstance(arguments, str):
            self.arguments_parts.append(arguments)

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


def _build_chat_payload(
    *,
    model: str,
    system: str,
    messages: list[AgentMessage],
    tools: list[AgentTool],
    reasoning_effort: str | None = None,
    max_tokens: int | None = None,
) -> dict[str, JSONValue]:
    payload: dict[str, JSONValue] = {
        "model": model,
        "stream": True,
        "messages": [
            _system_message(system),
            *[_message_to_openai(message) for message in messages],
        ],
    }
    payload["stream_options"] = {"include_usage": True}
    payload["store"] = False
    if max_tokens is not None:
        payload["max_completion_tokens"] = max_tokens
    _apply_chat_reasoning(
        payload,
        reasoning_effort=reasoning_effort,
    )
    if tools:
        payload["tools"] = [_tool_to_openai(tool) for tool in tools]
    return payload


def _apply_chat_reasoning(
    payload: dict[str, JSONValue],
    *,
    reasoning_effort: str | None,
) -> None:
    reasoning_enabled = reasoning_effort is not None and reasoning_effort != "none"
    if reasoning_enabled:
        payload["reasoning_effort"] = reasoning_effort


def _system_message(system: str) -> dict[str, JSONValue]:
    return {"role": "system", "content": system}


def _message_to_openai(message: AgentMessage) -> dict[str, JSONValue]:
    if isinstance(message, UserMessage):
        return {"role": "user", "content": message.text}

    if isinstance(message, AssistantMessage):
        item: dict[str, JSONValue] = {"role": "assistant", "content": message.text}
        thinking = [block for block in message.content if isinstance(block, ThinkingContent)]
        if thinking:
            signature = thinking[0].thinking_signature or "reasoning_content"
            if signature in {"reasoning_content", "reasoning", "thinking"}:
                item[signature] = "".join(block.thinking for block in thinking)
        if message.tool_calls:
            item["tool_calls"] = [
                _tool_call_to_openai(tool_call) for tool_call in message.tool_calls
            ]
        return item

    if isinstance(message, ToolResultMessage):
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id,
            "name": message.tool_name,
            "content": message.text,
        }
    return _message_to_openai(message_to_user(message))


def _tool_to_openai(tool: AgentTool) -> dict[str, JSONValue]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.input_schema),
        },
    }


def _tool_call_to_openai(tool_call: ToolCall) -> dict[str, JSONValue]:
    return {
        "id": tool_call.id,
        "type": "function",
        "function": {
            "name": tool_call.name,
            "arguments": dumps(tool_call.arguments),
        },
    }


def _first_choice(chunk: Mapping[str, Any]) -> Mapping[str, Any] | None:
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, Mapping):
        return None
    return choice


def _int_or_zero(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _parse_chunk_usage(raw: Mapping[str, Any]) -> Usage:
    """Parse an OpenAI-compatible ``usage`` payload into a Usage.

    Ports Pi's openai-completions.ts parseChunkUsage: ``cached_tokens`` are
    cache reads, writes are subtracted from the prompt to leave the fresh input,
    and ``completion_tokens`` already includes reasoning tokens. Cost is left
    unset (None) because Tau has no per-model pricing table.
    """
    prompt_tokens = _int_or_zero(raw.get("prompt_tokens"))
    prompt_details = raw.get("prompt_tokens_details")
    cached_tokens: int | None = None
    cache_write = 0
    if isinstance(prompt_details, Mapping):
        cached_tokens = int_or_none(prompt_details.get("cached_tokens"))
        cache_write = _int_or_zero(prompt_details.get("cache_write_tokens"))
    # Nullish fallback, matching Pi's `cached_tokens ?? prompt_cache_hit_tokens
    # ?? 0` (DeepSeek reports cache hits in prompt_cache_hit_tokens): a reported
    # 0 does not fall through.
    if cached_tokens is None:
        cached_tokens = int_or_none(raw.get("prompt_cache_hit_tokens"))
    cache_read = cached_tokens or 0
    fresh_input = max(0, prompt_tokens - cache_read - cache_write)
    output = _int_or_zero(raw.get("completion_tokens"))
    reasoning = None
    completion_details = raw.get("completion_tokens_details")
    if isinstance(completion_details, Mapping):
        reasoning = _int_or_zero(completion_details.get("reasoning_tokens"))
    return Usage(
        input=fresh_input,
        output=output,
        cache_read=cache_read,
        cache_write=cache_write,
        reasoning=reasoning,
        total_tokens=fresh_input + output + cache_read + cache_write,
    )


def _tool_call_deltas(delta: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    tool_calls = delta.get("tool_calls")
    if not isinstance(tool_calls, list):
        return []
    return [tool_call for tool_call in tool_calls if isinstance(tool_call, Mapping)]


def _thinking_delta(delta: Mapping[str, Any]) -> tuple[str, str] | None:
    for field_name in ("reasoning_content", "reasoning", "thinking"):
        value = delta.get(field_name)
        if isinstance(value, str) and value:
            return field_name, value
    return None
