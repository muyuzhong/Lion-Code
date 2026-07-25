"""Dynamic tool resolution via get_tools() in the harness."""

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


class TestDynamicTools(unittest.IsolatedAsyncioTestCase):
    async def test_get_tools_supplies_tools_per_turn(self) -> None:
        tool = _echo_tool()
        get_tools_calls: list[bool] = []

        def get_tools():
            get_tools_calls.append(True)
            return [tool]

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
                tools=[],  # empty static list - only get_tools can supply the tool
                get_tools=get_tools,
            )
        )

        async for _ in harness.prompt("hello"):
            pass

        # get_tools fired once per model request (2 turns)
        self.assertEqual(len(get_tools_calls), 2)
        # the dynamically supplied tool was found and executed cleanly
        messages = harness.messages
        self.assertEqual(
            [m.role for m in messages],
            ["user", "assistant", "toolResult", "assistant"],
        )
        self.assertEqual(messages[2].text, "echo:hi")
        self.assertFalse(messages[2].is_error)
        self.assertEqual(messages[3].text, "final")


if __name__ == "__main__":
    unittest.main(verbosity=2)
