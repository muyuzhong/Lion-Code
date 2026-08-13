"""Domain ModelQuery live Provider 适配器测试。"""

import unittest

from lion_code.core.messages import AssistantMessage, TextContent, UserMessage
from lion_code.core.provider_events import AssistantDoneEvent
from lion_code.model_query import ModelQueryUnavailableError, ProviderModelQuery
from lion_code.providers.fake import FakeProvider


class TestProviderModelQuery(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_typed_roles_and_uses_live_provider_and_model(self) -> None:
        first = FakeProvider([])
        second = FakeProvider(
            [
                [
                    AssistantDoneEvent(
                        reason="stop",
                        message=AssistantMessage(model="second", content="accepted"),
                    )
                ]
            ]
        )
        current = {"provider": first, "model": "first"}
        query = ProviderModelQuery(
            provider=lambda: current["provider"],
            model=lambda: current["model"],
            available=lambda: True,
        )
        messages = [
            UserMessage(content="evidence follows"),
            AssistantMessage(
                model="evidence",
                content=[TextContent(text="typed assistant evidence")],
            ),
        ]

        current.update(provider=second, model="second")
        result = await query.complete_messages(system="judge", messages=messages)

        self.assertEqual(result, "accepted")
        model, system, sent_messages, tools = second.calls[0]
        self.assertEqual(model, "second")
        self.assertEqual(system, "judge")
        self.assertEqual(tools, [])
        self.assertEqual(
            [message.role for message in sent_messages],
            [
                "user",
                "assistant",
            ],
        )

    async def test_unavailable_query_fails_before_provider_lookup(self) -> None:
        query = ProviderModelQuery(
            provider=lambda: (_ for _ in ()).throw(AssertionError("provider lookup")),
            model=lambda: "test",
            available=lambda: False,
        )

        with self.assertRaisesRegex(ModelQueryUnavailableError, "not configured"):
            await query.complete_text(system="classify", user="input")
