"""Core harness behavior contracts: text turns, tool-call loops, unknown tools."""

from __future__ import annotations

import asyncio
import unittest

from lion_code.core import (
    AgentEndEvent,
    AgentHarness,
    AgentHarnessConfig,
    AgentStartEvent,
    AgentTool,
    AgentToolResult,
    AssistantMessage,
    TextContent,
    ToolCall,
)
from lion_code.core.provider_events import AssistantDoneEvent

from .fakes import FakeProvider


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

    async def test_parallel_tools_run_concurrently(self) -> None:
        started = asyncio.Event()
        active = 0
        max_active = 0

        async def execute(tool_call_id, arguments, signal, on_update):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            if active == 2:
                started.set()
            await started.wait()
            active -= 1
            return AgentToolResult(content=[TextContent(text=tool_call_id)])

        provider = FakeProvider(
            [
                AssistantDoneEvent(
                    reason="toolUse",
                    message=AssistantMessage(
                        model="fake",
                        content=[
                            ToolCall(id="c1", name="one", arguments={}),
                            ToolCall(id="c2", name="two", arguments={}),
                        ],
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
        tools = [
            AgentTool(
                name=name,
                label=name,
                description=name,
                parameters={},
                execute_fn=execute,
                execution_mode="parallel",
            )
            for name in ("one", "two")
        ]
        harness = AgentHarness(
            AgentHarnessConfig(
                provider=provider,
                model="fake",
                system="test",
                tools=tools,
            )
        )

        async def consume() -> None:
            async for _ in harness.prompt("hello"):
                pass

        await asyncio.wait_for(consume(), timeout=1)

        self.assertEqual(max_active, 2)


class TestUnknownTool(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_tool_yields_error_result_not_exception(self) -> None:
        # The model calls a tool that is not registered. The loop must surface a
        # ToolResultMessage(is_error=True) and keep running, never raise.
        provider = FakeProvider(
            [
                AssistantDoneEvent(
                    reason="toolUse",
                    message=AssistantMessage(
                        model="fake",
                        content=[ToolCall(id="c1", name="ghost", arguments={})],
                        stop_reason="toolUse",
                    ),
                ),
                AssistantDoneEvent(
                    reason="stop",
                    message=AssistantMessage(
                        model="fake",
                        content=[TextContent(text="recovered")],
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
                tools=[],  # "ghost" is not registered
            )
        )

        async for _ in harness.prompt("hello"):
            pass

        messages = harness.messages
        self.assertEqual(
            [m.role for m in messages],
            ["user", "assistant", "toolResult", "assistant"],
        )
        self.assertTrue(messages[2].is_error)
        self.assertIn("ghost", messages[2].text)
        self.assertEqual(messages[3].text, "recovered")


if __name__ == "__main__":
    unittest.main(verbosity=2)
