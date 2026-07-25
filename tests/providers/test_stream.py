"""``canonicalize_provider_stream`` 行为契约测试。

直接构造 provider 内部事件序列，验证其被规范化为 Core 公共
``AssistantMessageEvent`` 的过程：文本/思考/工具调用通道切换、
finish_reason 归一化、provider 错误与未正常终止流的兜底。
"""

from __future__ import annotations

import unittest

from lion_code.core.messages import AssistantMessage, ToolCall
from lion_code.core.provider_events import (
    AssistantDoneEvent,
    AssistantErrorEvent,
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
from lion_code.providers._provider_events import (
    ProviderErrorEvent,
    ProviderResponseEndEvent,
    ProviderResponseStartEvent,
    ProviderRetryEvent,
    ProviderTextDeltaEvent,
    ProviderThinkingDeltaEvent,
    ProviderToolCallEvent,
)
from lion_code.providers.stream import canonicalize_provider_stream


async def _aiter(items: list[object]):
    for item in items:
        yield item  # type: ignore[misc]


async def _collect(events: list[object]) -> list[object]:
    return [
        event
        async for event in canonicalize_provider_stream(
            _aiter(events), api="test", provider="test", model="m"
        )
    ]


def _types(seq: list[object]) -> list[str]:
    return [type(event).__name__ for event in seq]


class TestCanonicalizeTextStream(unittest.IsolatedAsyncioTestCase):
    async def test_text_delta_start_end_done_sequence(self) -> None:
        seq = await _collect(
            [
                ProviderResponseStartEvent(model="m"),
                ProviderTextDeltaEvent(delta="hel"),
                ProviderTextDeltaEvent(delta="lo"),
                ProviderResponseEndEvent(message=AssistantMessage(content=[])),
            ]
        )

        self.assertEqual(
            _types(seq),
            [
                "AssistantStartEvent",
                "TextStartEvent",
                "TextDeltaEvent",
                "TextDeltaEvent",
                "TextEndEvent",
                "AssistantDoneEvent",
            ],
        )
        deltas = [event for event in seq if isinstance(event, TextDeltaEvent)]
        self.assertEqual([d.delta for d in deltas], ["hel", "lo"])
        end = next(event for event in seq if isinstance(event, TextEndEvent))
        self.assertEqual(end.content, "hello")
        done = next(event for event in seq if isinstance(event, AssistantDoneEvent))
        self.assertEqual(done.reason, "stop")
        self.assertEqual(done.message.text, "hello")
        self.assertEqual(done.message.api, "test")
        self.assertEqual(done.message.provider, "test")
        self.assertEqual(done.message.model, "m")

    async def test_implicit_start_when_first_event_is_content(self) -> None:
        # 没有 response_start 时，首个内容事件前应自动补发 AssistantStartEvent。
        seq = await _collect([ProviderTextDeltaEvent(delta="hi")])

        self.assertIsInstance(seq[0], AssistantStartEvent)
        self.assertIsInstance(seq[1], TextStartEvent)
        self.assertIsInstance(seq[2], TextDeltaEvent)


class TestCanonicalizeThinkingStream(unittest.IsolatedAsyncioTestCase):
    async def test_thinking_block_emits_start_delta_end(self) -> None:
        seq = await _collect(
            [
                ProviderResponseStartEvent(model="m"),
                ProviderThinkingDeltaEvent(delta="plan"),
                ProviderThinkingDeltaEvent(delta="?"),
                ProviderResponseEndEvent(message=AssistantMessage(content=[])),
            ]
        )

        self.assertEqual(
            _types(seq),
            [
                "AssistantStartEvent",
                "ThinkingStartEvent",
                "ThinkingDeltaEvent",
                "ThinkingDeltaEvent",
                "ThinkingEndEvent",
                "AssistantDoneEvent",
            ],
        )
        end = next(event for event in seq if isinstance(event, ThinkingEndEvent))
        self.assertEqual(end.content, "plan?")
        done = next(event for event in seq if isinstance(event, AssistantDoneEvent))
        self.assertEqual(done.message.thinking_text, "plan?")


class TestCanonicalizeToolCall(unittest.IsolatedAsyncioTestCase):
    async def test_tool_call_emits_start_end_and_tooluse_reason(self) -> None:
        tool_call = ToolCall(id="c1", name="echo", arguments={"msg": "hi"})
        seq = await _collect(
            [
                ProviderResponseStartEvent(model="m"),
                ProviderToolCallEvent(tool_call=tool_call),
                ProviderResponseEndEvent(message=AssistantMessage(content=[])),
            ]
        )

        self.assertEqual(
            _types(seq),
            [
                "AssistantStartEvent",
                "ToolCallStartEvent",
                "ToolCallEndEvent",
                "AssistantDoneEvent",
            ],
        )
        end = next(event for event in seq if isinstance(event, ToolCallEndEvent))
        self.assertEqual(end.tool_call.id, "c1")
        done = next(event for event in seq if isinstance(event, AssistantDoneEvent))
        self.assertEqual(done.reason, "toolUse")
        self.assertEqual(done.message.tool_calls[0].name, "echo")


class TestCanonicalizeErrors(unittest.IsolatedAsyncioTestCase):
    async def test_provider_error_becomes_assistant_error_event(self) -> None:
        seq = await _collect(
            [
                ProviderResponseStartEvent(model="m"),
                ProviderErrorEvent(message="boom", data={"status_code": 500}),
            ]
        )

        self.assertIsInstance(seq[0], AssistantStartEvent)
        error = seq[-1]
        self.assertIsInstance(error, AssistantErrorEvent)
        self.assertEqual(error.reason, "error")
        self.assertEqual(error.error.stop_reason, "error")
        self.assertEqual(error.error.error_message, "boom")

    async def test_stream_without_terminal_event_yields_error(self) -> None:
        # 流未以 response_end / error 收尾时，必须兜底为 AssistantErrorEvent。
        seq = await _collect([ProviderResponseStartEvent(model="m")])

        self.assertIsInstance(seq[-1], AssistantErrorEvent)
        self.assertIn("without a terminal event", seq[-1].error.error_message)

    async def test_retry_events_are_ignored(self) -> None:
        # ProviderRetryEvent 是 provider 内部事件，规范化器应静默跳过。
        seq = await _collect(
            [
                ProviderResponseStartEvent(model="m"),
                ProviderRetryEvent(
                    attempt=2,
                    max_attempts=3,
                    delay_seconds=0.0,
                    message="retrying",
                ),
                ProviderTextDeltaEvent(delta="ok"),
                ProviderResponseEndEvent(message=AssistantMessage(content=[])),
            ]
        )

        self.assertNotIn("ProviderRetryEvent", _types(seq))
        # 文本流仍应正常产出。
        self.assertTrue(any(isinstance(e, TextEndEvent) for e in seq))
        self.assertIsInstance(seq[-1], AssistantDoneEvent)


if __name__ == "__main__":
    unittest.main(verbosity=2)
