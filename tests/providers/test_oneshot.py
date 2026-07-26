"""complete_text 一次性补全助手的契约测试。"""

from __future__ import annotations

import unittest

from lion_code.core.messages import AssistantMessage, TextContent, UserMessage
from lion_code.core.provider_events import AssistantDoneEvent, AssistantErrorEvent
from lion_code.providers import FakeProvider
from lion_code.providers.oneshot import complete_text


class TestCompleteText(unittest.IsolatedAsyncioTestCase):
    async def test_returns_final_assistant_text(self) -> None:
        provider = FakeProvider(
            [
                [
                    AssistantDoneEvent(
                        reason="stop",
                        message=AssistantMessage(
                            model="fake",
                            content=[TextContent(text="answer")],
                            stop_reason="stop",
                        ),
                    )
                ]
            ]
        )
        text = await complete_text(
            provider, model="m", system="s", messages=[UserMessage(content="q")]
        )
        self.assertEqual(text, "answer")
        self.assertEqual(provider.calls[0][0], "m")

    async def test_error_event_raises(self) -> None:
        provider = FakeProvider(
            [
                [
                    AssistantErrorEvent(
                        reason="error",
                        error=AssistantMessage(
                            model="fake",
                            content=[],
                            stop_reason="error",
                            error_message="boom",
                        ),
                    )
                ]
            ]
        )
        with self.assertRaises(RuntimeError):
            await complete_text(
                provider, model="m", system="s", messages=[UserMessage(content="q")]
            )


if __name__ == "__main__":
    unittest.main()
