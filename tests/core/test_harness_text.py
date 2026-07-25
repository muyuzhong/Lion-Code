"""Pure-text agent harness response: a single stop turn reaches history."""

from __future__ import annotations

import unittest

from lion_code.core import (
    AgentEndEvent,
    AgentHarness,
    AgentHarnessConfig,
    AgentStartEvent,
    AssistantMessage,
    TextContent,
)
from lion_code.core.provider_events import AssistantDoneEvent

from fakes import FakeProvider


class TestHarnessTextResponse(unittest.IsolatedAsyncioTestCase):
    async def test_text_response(self) -> None:
        provider = FakeProvider(
            [
                AssistantDoneEvent(
                    reason="stop",
                    message=AssistantMessage(
                        model="fake",
                        content=[TextContent(text="done")],
                    ),
                ),
            ]
        )

        harness = AgentHarness(
            AgentHarnessConfig(
                provider=provider,
                model="fake",
                system="test",
            )
        )

        events = [event async for event in harness.prompt("hello")]

        self.assertEqual(harness.messages[-1].text, "done")
        self.assertEqual(harness.messages[0].text, "hello")
        self.assertEqual(provider.call_count, 1)
        self.assertIsInstance(events[0], AgentStartEvent)
        self.assertIsInstance(events[-1], AgentEndEvent)


if __name__ == "__main__":
    unittest.main(verbosity=2)
