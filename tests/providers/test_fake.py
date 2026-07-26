"""FakeProvider 回放契约测试。"""

from __future__ import annotations

import unittest

from lion_code.core.harness import SimpleCancellationToken
from lion_code.core.messages import AssistantMessage
from lion_code.providers import FakeProvider
from lion_code.providers.events import AssistantDoneEvent, TextDeltaEvent


def _message() -> AssistantMessage:
    return AssistantMessage(model="fake", content=[], stop_reason="stop")


def _done() -> AssistantDoneEvent:
    return AssistantDoneEvent(reason="stop", message=_message())


def _delta(text: str) -> TextDeltaEvent:
    return TextDeltaEvent(content_index=0, delta=text, partial=_message())


class TestFakeProvider(unittest.IsolatedAsyncioTestCase):
    async def test_replays_streams_in_order_and_records_calls(self) -> None:
        first = [_delta("你"), _done()]
        second = [_done()]
        provider = FakeProvider([first, second])

        got_first = [
            event
            async for event in provider.stream_response(
                model="m1", system="s1", messages=[], tools=[]
            )
        ]
        got_second = [
            event
            async for event in provider.stream_response(
                model="m2", system="s2", messages=[], tools=[]
            )
        ]

        self.assertEqual(got_first, first)
        self.assertEqual(got_second, second)
        self.assertEqual(
            [(call[0], call[1]) for call in provider.calls],
            [("m1", "s1"), ("m2", "s2")],
        )

    async def test_exhausted_streams_yield_empty(self) -> None:
        provider = FakeProvider([])
        events = [
            event
            async for event in provider.stream_response(
                model="m", system="s", messages=[], tools=[]
            )
        ]
        self.assertEqual(events, [])

    async def test_cancelled_signal_stops_replay(self) -> None:
        signal = SimpleCancellationToken()
        signal.cancel()
        provider = FakeProvider([[_delta("x"), _done()]])
        events = [
            event
            async for event in provider.stream_response(
                model="m", system="s", messages=[], tools=[], signal=signal
            )
        ]
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
