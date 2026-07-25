"""Tool-call closed loop through the harness.

Verifies the transcript order is exactly:
    UserMessage -> AssistantMessage(tool call) -> ToolResultMessage ->
    AssistantMessage(final text)
"""

from __future__ import annotations

import unittest

from lion_code.core import (
    AgentHarness,
    AgentHarnessConfig,
    AgentTool,
    AgentToolResult,
    AssistantMessage,
    TextContent,
    ToolCall,
)
from lion_code.core.provider_events import AssistantDoneEvent

from fakes import FakeProvider


def _echo_tool() -> AgentTool:
    async def execute(tool_call_id, arguments, signal, on_update):
        return AgentToolResult(
            content=[TextContent(text=f"echo:{arguments.get('msg', '')}")],
            details={},
        )

    return AgentTool(
        name="echo",
        label="Echo",
        description="echo the msg argument",
        parameters={},
        execute_fn=execute,
    )


class TestHarnessToolLoop(unittest.IsolatedAsyncioTestCase):
    async def test_tool_call_closed_loop(self) -> None:
        provider = FakeProvider(
            [
                AssistantDoneEvent(
                    reason="toolUse",
                    message=AssistantMessage(
                        model="fake",
                        content=[ToolCall(id="c1", name="echo", arguments={"msg": "hi"})],
                        stop_reason="toolUse",
                    ),
                ),
                AssistantDoneEvent(
                    reason="stop",
                    message=AssistantMessage(
                        model="fake",
                        content=[TextContent(text="final")],
                        stop_reason="stop",
                    ),
                ),
            ]
        )

        harness = AgentHarness(
            AgentHarnessConfig(
                provider=provider,
                model="fake",
                system="test",
                tools=[_echo_tool()],
            )
        )

        async for _ in harness.prompt("hello"):
            pass

        messages = harness.messages
        self.assertEqual(
            [m.role for m in messages],
            ["user", "assistant", "toolResult", "assistant"],
        )
        self.assertEqual(messages[1].tool_calls[0].name, "echo")
        self.assertEqual(messages[2].text, "echo:hi")
        self.assertFalse(messages[2].is_error)
        self.assertEqual(messages[3].text, "final")
        self.assertEqual(provider.call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
