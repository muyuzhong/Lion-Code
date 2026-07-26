"""``AnthropicProvider`` 流式解析与控制流测试。

通过 ``httpx.MockTransport`` 注入伪造的 Anthropic Messages API SSE 响应，
覆盖：文本与 usage、工具调用、思考块、HTTP 错误、取消。不发起真实请求。
"""

from __future__ import annotations

import json
import unittest
from typing import Any

import httpx

from lion_code.core.messages import UserMessage
from lion_code.core.provider_events import (
    AssistantDoneEvent,
    AssistantErrorEvent,
    TextDeltaEvent,
    ThinkingDeltaEvent,
    ThinkingEndEvent,
    ToolCallEndEvent,
)
from lion_code.providers.anthropic import AnthropicProvider
from lion_code.providers.config import AnthropicConfig


def _config(**overrides: Any) -> AnthropicConfig:
    kwargs: dict[str, Any] = dict(
        api_key="test-key",
        base_url="https://example.test/v1",
        max_retries=2,
        max_retry_delay_seconds=0.0,
    )
    kwargs.update(overrides)
    return AnthropicConfig(**kwargs)


def _sse(*items: Any) -> bytes:
    parts: list[str] = []
    for item in items:
        payload = item if isinstance(item, str) else json.dumps(item)
        parts.append(f"data: {payload}\n\n")
    return "".join(parts).encode()


def _types(seq: list[object]) -> list[str]:
    return [type(e).__name__ for e in seq]


class _CancelSignal:
    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled


class TestAnthropicText(unittest.IsolatedAsyncioTestCase):
    async def test_text_parse_usage_and_request_shape(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(
                200,
                content=_sse(
                    {"type": "message_start", "message": {"usage": {"input_tokens": 4, "output_tokens": 0}}},
                    {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hel"}},
                    {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "lo"}},
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": "end_turn"},
                        "usage": {"input_tokens": 4, "output_tokens": 2},
                    },
                ),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = AnthropicProvider(_config(), client=client)
            events = [
                e
                async for e in provider.stream_response(
                    model="claude-3-5",
                    system="s",
                    messages=[UserMessage(content="hi")],
                    tools=[],
                )
            ]

        self.assertEqual(
            _types(events),
            [
                "AssistantStartEvent",
                "TextStartEvent",
                "TextDeltaEvent",
                "TextDeltaEvent",
                "TextEndEvent",
                "AssistantDoneEvent",
            ],
        )
        done = next(e for e in events if isinstance(e, AssistantDoneEvent))
        self.assertEqual(done.message.text, "hello")
        self.assertEqual(done.reason, "stop")
        self.assertEqual(done.message.usage.input, 4)
        self.assertEqual(done.message.usage.output, 2)
        self.assertEqual(done.message.usage.total_tokens, 6)

        # 请求形状：走 /messages，带 x-api-key 与 anthropic-version。
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].url.path, "/v1/messages")
        self.assertEqual(seen[0].headers["x-api-key"], "test-key")
        self.assertEqual(seen[0].headers["anthropic-version"], "2023-06-01")
        body = json.loads(seen[0].content)
        self.assertEqual(body["model"], "claude-3-5")
        self.assertEqual(body["stream"], True)
        self.assertEqual(body["system"], "s")
        self.assertEqual(body["messages"][0], {"role": "user", "content": "hi"})


class TestAnthropicToolUse(unittest.IsolatedAsyncioTestCase):
    async def test_tool_use_accumulates_streamed_arguments(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=_sse(
                    {
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {"type": "tool_use", "id": "tool-1", "name": "echo"},
                    },
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "input_json_delta", "partial_json": '{"msg":'},
                    },
                    {
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "input_json_delta", "partial_json": '"hi"}'},
                    },
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": "tool_use"},
                        "usage": {"input_tokens": 4, "output_tokens": 3},
                    },
                ),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = AnthropicProvider(_config(), client=client)
            events = [
                e
                async for e in provider.stream_response(
                    model="claude-3-5",
                    system="s",
                    messages=[UserMessage(content="hi")],
                    tools=[],
                )
            ]

        end = next(e for e in events if isinstance(e, ToolCallEndEvent))
        self.assertEqual(end.tool_call.id, "tool-1")
        self.assertEqual(end.tool_call.name, "echo")
        self.assertEqual(end.tool_call.arguments, {"msg": "hi"})
        done = next(e for e in events if isinstance(e, AssistantDoneEvent))
        self.assertEqual(done.reason, "toolUse")
        self.assertEqual(len(done.message.tool_calls), 1)


class TestAnthropicThinking(unittest.IsolatedAsyncioTestCase):
    async def test_thinking_block_precedes_text(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=_sse(
                    {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "plan"}},
                    {"type": "content_block_delta", "delta": {"type": "signature_delta", "signature": "sig"}},
                    {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "answer"}},
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": "end_turn"},
                        "usage": {"input_tokens": 3, "output_tokens": 2},
                    },
                ),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = AnthropicProvider(_config(), client=client)
            events = [
                e
                async for e in provider.stream_response(
                    model="claude-3-5",
                    system="s",
                    messages=[UserMessage(content="hi")],
                    tools=[],
                )
            ]

        # 思考块先开始，文本切换时思考块结束。
        thinking_end = next(e for e in events if isinstance(e, ThinkingEndEvent))
        self.assertEqual(thinking_end.content, "plan")
        done = next(e for e in events if isinstance(e, AssistantDoneEvent))
        self.assertEqual(done.message.thinking_text, "plan")
        self.assertEqual(done.message.text, "answer")
        # 思考块的 signature 被回放到最终消息上。
        thinking_block = done.message.content[0]
        self.assertEqual(thinking_block.thinking_signature, "sig")


class TestAnthropicErrorsAndCancellation(unittest.IsolatedAsyncioTestCase):
    async def test_http_400_yields_error_without_retry(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, content=b'{"error":{"message":"bad request"}}')

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = AnthropicProvider(_config(max_retries=2), client=client)
            events = [
                e
                async for e in provider.stream_response(
                    model="claude-3-5",
                    system="s",
                    messages=[UserMessage(content="hi")],
                    tools=[],
                )
            ]

        self.assertIsInstance(events[-1], AssistantErrorEvent)
        self.assertNotIn("AssistantDoneEvent", _types(events))

    async def test_cancellation_aborts_mid_stream(self) -> None:
        signal = _CancelSignal()

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=_sse(
                    {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hel"}},
                    {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "lo"}},
                    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
                ),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = AnthropicProvider(_config(), client=client)
            events: list[object] = []
            async for event in provider.stream_response(
                model="claude-3-5",
                system="s",
                messages=[UserMessage(content="hi")],
                tools=[],
                signal=signal,
            ):
                events.append(event)
                if isinstance(event, TextDeltaEvent):
                    signal.cancel()

        deltas = [e.delta for e in events if isinstance(e, TextDeltaEvent)]
        self.assertEqual(deltas, ["hel"])
        self.assertNotIn("AssistantDoneEvent", _types(events))
        self.assertIsInstance(events[-1], AssistantErrorEvent)


class TestAnthropicThinkingPayload(unittest.IsolatedAsyncioTestCase):
    """thinking 三种模式的请求 payload 形状(与上游 0.3.3 对齐)。"""

    async def _request_body(self, config: AnthropicConfig) -> dict[str, Any]:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(
                200,
                content=_sse(
                    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}
                ),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = AnthropicProvider(config, client=client)
            async for _ in provider.stream_response(
                model="claude-3-5",
                system="s",
                messages=[UserMessage(content="hi")],
                tools=[],
            ):
                pass
        return json.loads(seen[0].content)

    async def test_disabled_mode_sends_explicit_disabled_payload(self) -> None:
        body = await self._request_body(_config(thinking_mode="disabled"))
        self.assertEqual(body["thinking"], {"type": "disabled"})

    async def test_budget_mode_sends_enabled_with_budget(self) -> None:
        body = await self._request_body(_config(thinking_budget_tokens=2048))
        self.assertEqual(
            body["thinking"], {"type": "enabled", "budget_tokens": 2048}
        )

    async def test_default_without_budget_omits_thinking(self) -> None:
        body = await self._request_body(_config())
        self.assertNotIn("thinking", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
