"""Cancellation contracts: in-flight runs abort via the provider stream."""

from __future__ import annotations

import unittest

from lion_code.core import (
    AgentEndEvent,
    AgentHarness,
    AgentHarnessConfig,
    AgentTool,
    AgentToolResult,
    AssistantMessage,
    TextContent,
    ToolCall,
    TurnEndEvent,
)
from lion_code.core.provider_events import AssistantDoneEvent, AssistantErrorEvent

from .fakes import FakeProvider


def _noop_tool() -> AgentTool:
    async def execute(tool_call_id, arguments, signal, on_update):
        return AgentToolResult(content=[TextContent(text="ok")], details={})

    return AgentTool(
        name="noop",
        label="Noop",
        description="no-op tool",
        parameters={},
        execute_fn=execute,
    )


class TestHarnessCancel(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_aborts_run_after_turn(self) -> None:
        # Turn 1 requests a tool call; turn 2 would answer with final text, but we
        # cancel between turns so the next provider stream aborts.
        provider = FakeProvider(
            [
                AssistantDoneEvent(
                    reason="toolUse",
                    message=AssistantMessage(
                        model="fake",
                        content=[ToolCall(id="c1", name="noop", arguments={})],
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
                tools=[_noop_tool()],
            )
        )

        events = []
        cancelled = False
        async for event in harness.prompt("hello"):
            events.append(event)
            if not cancelled and isinstance(event, TurnEndEvent):
                harness.cancel()
                cancelled = True

        # the run terminated after the aborted stream
        self.assertTrue(any(isinstance(e, AgentEndEvent) for e in events))
        # provider was called twice: turn 1 + the aborted turn 2
        self.assertEqual(provider.call_count, 2)
        # the cancelled stream produced an aborted assistant as the final message
        self.assertEqual(harness.messages[-1].stop_reason, "aborted")
        # the never-reached "final" text never entered history
        self.assertNotIn("final", [getattr(m, "text", "") for m in harness.messages])

    async def test_error_event_reason_overrides_message_stop_reason(self) -> None:
        provider = FakeProvider(
            [
                AssistantErrorEvent(
                    reason="aborted",
                    error=AssistantMessage(model="fake"),
                )
            ]
        )
        harness = AgentHarness(
            AgentHarnessConfig(
                provider=provider,
                model="fake",
                system="test",
            )
        )

        async for _ in harness.prompt("hello"):
            pass

        self.assertEqual(harness.messages[-1].stop_reason, "aborted")


if __name__ == "__main__":
    unittest.main(verbosity=2)
