"""``UsageObserver`` 的事件过滤与 Ledger 转发测试。"""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from lion_code.core import (
    AgentStartEvent,
    AssistantMessage,
    MessageEndEvent,
    Usage,
    UserMessage,
)
from lion_code.observers import UsageObserver
from lion_code.usage import UsageLedger


class TestUsageObserver(unittest.IsolatedAsyncioTestCase):
    async def test_forwards_each_assistant_terminal_event_once(self) -> None:
        ledger = Mock(spec=UsageLedger)
        observer = UsageObserver(ledger)
        usage = Usage(input=5, output=3)

        with patch("lion_code.observers.usage.time", return_value=123.0):
            await observer.handle(
                MessageEndEvent(message=AssistantMessage(usage=usage))
            )

        ledger.record_model_usage.assert_called_once_with(
            usage,
            response_at=123.0,
        )

    async def test_ignores_non_assistant_message_end(self) -> None:
        ledger = Mock(spec=UsageLedger)
        observer = UsageObserver(ledger)

        await observer.handle(
            MessageEndEvent(message=UserMessage(content="not assistant"))
        )

        ledger.record_model_usage.assert_not_called()

    async def test_ignores_non_message_end_events(self) -> None:
        ledger = Mock(spec=UsageLedger)
        observer = UsageObserver(ledger)

        await observer.handle(AgentStartEvent())

        ledger.record_model_usage.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
