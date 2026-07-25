"""``UsageObserver`` 累计行为测试。"""

from __future__ import annotations

import unittest

from lion_code.core import (
    AgentStartEvent,
    AssistantMessage,
    MessageEndEvent,
    Usage,
    UsageCost,
    UserMessage,
)
from lion_code.observers import UsageObserver


class TestUsageObserver(unittest.IsolatedAsyncioTestCase):
    async def test_accumulates_across_assistant_messages(self) -> None:
        observer = UsageObserver()
        await observer.handle(
            MessageEndEvent(message=AssistantMessage(usage=Usage(input=5, output=3, total_tokens=8)))
        )
        await observer.handle(
            MessageEndEvent(message=AssistantMessage(usage=Usage(input=2, output=1, total_tokens=3)))
        )

        totals = observer.totals
        self.assertEqual(totals.input_tokens, 7)
        self.assertEqual(totals.output_tokens, 4)
        self.assertEqual(totals.cache_read_tokens, 0)

    async def test_accumulates_reasoning_and_cost(self) -> None:
        observer = UsageObserver()
        await observer.handle(
            MessageEndEvent(
                message=AssistantMessage(
                    usage=Usage(input=5, output=3, reasoning=10, cost=UsageCost(total=0.01))
                )
            )
        )

        totals = observer.totals
        self.assertEqual(totals.reasoning_tokens, 10)
        self.assertAlmostEqual(totals.cost_usd, 0.01)

    async def test_ignores_non_assistant_message_end(self) -> None:
        observer = UsageObserver()
        await observer.handle(MessageEndEvent(message=UserMessage(content="not assistant")))

        self.assertEqual(observer.totals.input_tokens, 0)

    async def test_ignores_non_message_end_events(self) -> None:
        observer = UsageObserver()
        await observer.handle(AgentStartEvent())

        self.assertEqual(observer.totals.input_tokens, 0)

    async def test_totals_snapshot_does_not_alias_internal_state(self) -> None:
        # 同一 MessageEndEvent 只累计一次；快照被外部修改不影响内部累计。
        observer = UsageObserver()
        await observer.handle(
            MessageEndEvent(message=AssistantMessage(usage=Usage(input=5, output=3)))
        )

        snapshot = observer.totals
        snapshot.input_tokens = 999

        self.assertEqual(observer.totals.input_tokens, 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
