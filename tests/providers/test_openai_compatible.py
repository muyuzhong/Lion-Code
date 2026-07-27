"""``OpenAICompatibleProvider`` 流式解析与控制流测试。

通过 ``httpx.MockTransport`` 注入伪造的 SSE 响应，覆盖：
文本解析与 usage、单个/交错工具调用、``/chat/completions`` 与
``/responses`` 路由、HTTP 429 重试、网络错误、取消。
不发起任何真实网络请求。
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
    TextEndEvent,
    ToolCallEndEvent,
)
from lion_code.providers.config import OpenAICompatibleConfig
from lion_code.providers.openai_compatible import OpenAICompatibleProvider


def _config(**overrides: Any) -> OpenAICompatibleConfig:
    kwargs: dict[str, Any] = dict(
        api_key="test-key",
        base_url="https://example.test/v1",
        max_retries=2,
        max_retry_delay_seconds=0.0,
    )
    kwargs.update(overrides)
    return OpenAICompatibleConfig(**kwargs)


def _sse(*items: Any) -> bytes:
    """把若干 dict（或裸字符串如 ``[DONE]``）拼成 SSE 字节流。"""
    parts: list[str] = []
    for item in items:
        payload = item if isinstance(item, str) else json.dumps(item)
        parts.append(f"data: {payload}\n\n")
    return "".join(parts).encode()


def _chat_delta(delta: dict[str, Any], *, finish_reason: str | None = None, usage: dict[str, Any] | None = None) -> dict[str, Any]:
    choice: dict[str, Any] = {"delta": delta}
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    chunk: dict[str, Any] = {"choices": [choice]}
    if usage is not None:
        chunk["usage"] = usage
    return chunk


def _types(seq: list[object]) -> list[str]:
    return [type(e).__name__ for e in seq]


class _CancelSignal:
    """可外部翻转的 ``CancellationToken`` 测试替身。"""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled


class TestOpenAIChatCompletionsText(unittest.IsolatedAsyncioTestCase):
    async def test_text_parse_usage_and_request_shape(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(
                200,
                content=_sse(
                    _chat_delta({"content": "hel"}),
                    _chat_delta({"content": "lo"}),
                    _chat_delta({}, finish_reason="stop", usage={"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7}),
                    "[DONE]",
                ),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(_config(), client=client)
            events = [
                e
                async for e in provider.stream_response(
                    model="gpt-4",
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
        deltas = [e.delta for e in events if isinstance(e, TextDeltaEvent)]
        self.assertEqual(deltas, ["hel", "lo"])
        end = next(e for e in events if isinstance(e, TextEndEvent))
        self.assertEqual(end.content, "hello")
        done = next(e for e in events if isinstance(e, AssistantDoneEvent))
        self.assertEqual(done.reason, "stop")
        self.assertEqual(done.message.text, "hello")
        self.assertEqual(done.message.usage.input, 5)
        self.assertEqual(done.message.usage.output, 2)
        self.assertEqual(done.message.usage.total_tokens, 7)

        # 请求形状：走 chat/completions，带 Bearer 鉴权，载荷含模型与系统消息。
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].url.path, "/v1/chat/completions")
        self.assertEqual(seen[0].headers["Authorization"], "Bearer test-key")
        body = json.loads(seen[0].content)
        self.assertEqual(body["model"], "gpt-4")
        self.assertEqual(body["stream"], True)
        self.assertEqual(body["messages"][0], {"role": "system", "content": "s"})
        self.assertEqual(body["messages"][1], {"role": "user", "content": "hi"})


class TestOpenAIChatCompletionsToolCalls(unittest.IsolatedAsyncioTestCase):
    async def test_single_tool_call(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=_sse(
                    _chat_delta(
                        {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-1",
                                    "function": {"name": "echo", "arguments": json.dumps({"msg": "hi"})},
                                }
                            ]
                        }
                    ),
                    _chat_delta({}, finish_reason="tool_calls"),
                    "[DONE]",
                ),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(_config(), client=client)
            events = [
                e
                async for e in provider.stream_response(
                    model="gpt-4",
                    system="s",
                    messages=[UserMessage(content="hi")],
                    tools=[],
                )
            ]

        self.assertEqual(
            _types(events),
            ["AssistantStartEvent", "ToolCallStartEvent", "ToolCallEndEvent", "AssistantDoneEvent"],
        )
        end = next(e for e in events if isinstance(e, ToolCallEndEvent))
        self.assertEqual(end.tool_call.id, "call-1")
        self.assertEqual(end.tool_call.name, "echo")
        self.assertEqual(end.tool_call.arguments, {"msg": "hi"})
        done = next(e for e in events if isinstance(e, AssistantDoneEvent))
        self.assertEqual(done.reason, "toolUse")
        self.assertEqual(len(done.message.tool_calls), 1)

    async def test_two_interleaved_tool_calls(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=_sse(
                    _chat_delta(
                        {
                            "tool_calls": [
                                {"index": 0, "id": "c1", "function": {"name": "one", "arguments": "{}"}}
                            ]
                        }
                    ),
                    _chat_delta(
                        {
                            "tool_calls": [
                                {"index": 1, "id": "c2", "function": {"name": "two", "arguments": "{}"}}
                            ]
                        }
                    ),
                    _chat_delta(
                        {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": '"more"'}}
                            ]
                        }
                    ),
                    _chat_delta({}, finish_reason="tool_calls"),
                    "[DONE]",
                ),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(_config(), client=client)
            events = [
                e
                async for e in provider.stream_response(
                    model="gpt-4",
                    system="s",
                    messages=[UserMessage(content="hi")],
                    tools=[],
                )
            ]

        done = next(e for e in events if isinstance(e, AssistantDoneEvent))
        names = [tc.name for tc in done.message.tool_calls]
        self.assertEqual(names, ["one", "two"])
        self.assertEqual([tc.id for tc in done.message.tool_calls], ["c1", "c2"])
        # 两个工具调用各产出 start/end。
        self.assertEqual(
            _types(events).count("ToolCallStartEvent"),
            2,
        )
        self.assertEqual(_types(events).count("ToolCallEndEvent"), 2)


class TestOpenAIResponsesApi(unittest.IsolatedAsyncioTestCase):
    async def test_responses_text_and_routing(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(
                200,
                content=_sse(
                    {"type": "response.created"},
                    {"type": "response.output_text.delta", "delta": "hel"},
                    {"type": "response.output_text.delta", "delta": "lo"},
                    {
                        "type": "response.completed",
                        "response": {
                            "status": "completed",
                            "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
                        },
                    },
                ),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(_config(), client=client)
            events = [
                e
                async for e in provider.stream_response(
                    model="gpt-5.5",
                    system="s",
                    messages=[UserMessage(content="hi")],
                    tools=[],
                )
            ]

        done = next(e for e in events if isinstance(e, AssistantDoneEvent))
        self.assertEqual(done.message.text, "hello")
        self.assertEqual(done.reason, "stop")
        self.assertEqual(done.message.usage.input, 3)
        self.assertEqual(done.message.usage.output, 2)
        self.assertEqual(done.message.usage.total_tokens, 5)
        # gpt-5.5 必须路由到 /responses 而非 /chat/completions。
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].url.path, "/v1/responses")


class TestOpenAIRetryAndErrors(unittest.IsolatedAsyncioTestCase):
    async def test_http_429_retries_then_succeeds(self) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if len(calls) == 1:
                return httpx.Response(429, content=b'{"error":{"message":"rate limited"}}')
            return httpx.Response(
                200,
                content=_sse(
                    _chat_delta({"content": "ok"}),
                    _chat_delta({}, finish_reason="stop"),
                    "[DONE]",
                ),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(_config(max_retries=2), client=client)
            events = [
                e
                async for e in provider.stream_response(
                    model="gpt-4",
                    system="s",
                    messages=[UserMessage(content="hi")],
                    tools=[],
                )
            ]

        # 重试一次后成功：两次请求，最终得到文本 done。
        self.assertEqual(len(calls), 2)
        done = next(e for e in events if isinstance(e, AssistantDoneEvent))
        self.assertEqual(done.message.text, "ok")

    async def test_network_error_without_retry_yields_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(_config(max_retries=0), client=client)
            events = [
                e
                async for e in provider.stream_response(
                    model="gpt-4",
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
                    _chat_delta({"content": "hel"}),
                    _chat_delta({"content": "lo"}),
                    _chat_delta({}, finish_reason="stop"),
                    "[DONE]",
                ),
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = OpenAICompatibleProvider(_config(), client=client)
            events: list[object] = []
            async for event in provider.stream_response(
                model="gpt-4",
                system="s",
                messages=[UserMessage(content="hi")],
                tools=[],
                signal=signal,
            ):
                events.append(event)
                if isinstance(event, TextDeltaEvent):
                    signal.cancel()

        deltas = [e.delta for e in events if isinstance(e, TextDeltaEvent)]
        # 取消后后续增量不再产出，流被中断。
        self.assertEqual(deltas, ["hel"])
        self.assertNotIn("AssistantDoneEvent", _types(events))
        self.assertNotIn("TextEndEvent", _types(events))
        self.assertIsInstance(events[-1], AssistantErrorEvent)
        self.assertEqual(events[-1].reason, "aborted")
        self.assertEqual(events[-1].error.stop_reason, "aborted")


if __name__ == "__main__":
    unittest.main(verbosity=2)
