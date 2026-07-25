"""Dynamic configuration contracts: per-turn tools, system prompt, context shaping."""

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
    UserMessage,
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


def _tool_named(name: str) -> AgentTool:
    async def execute(tool_call_id, arguments, signal, on_update):
        return AgentToolResult(content=[TextContent(text=name)], details={})

    return AgentTool(
        name=name,
        label=name,
        description=name,
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
        messages = harness.messages
        self.assertEqual(
            [m.role for m in messages],
            ["user", "assistant", "toolResult", "assistant"],
        )
        self.assertEqual(messages[2].text, "echo:hi")
        self.assertFalse(messages[2].is_error)
        self.assertEqual(messages[3].text, "final")

    async def test_get_tools_reflects_per_turn_changes(self) -> None:
        # Turn 1 exposes only tool A; executing A flips state so turn 2 exposes A+B.
        # Asserts the provider's *second* request observes tool B.
        state = {"b_active": False}

        async def execute_a(tool_call_id, arguments, signal, on_update):
            state["b_active"] = True
            return AgentToolResult(content=[TextContent(text="A")], details={})

        tool_a = AgentTool(
            name="A", label="A", description="A", parameters={}, execute_fn=execute_a
        )
        tool_b = _tool_named("B")

        def get_tools():
            return [tool_a] + ([tool_b] if state["b_active"] else [])

        provider = FakeProvider(
            [
                AssistantDoneEvent(
                    reason="toolUse",
                    message=AssistantMessage(
                        model="fake",
                        content=[ToolCall(id="c1", name="A", arguments={})],
                        stop_reason="toolUse",
                    ),
                ),
                AssistantDoneEvent(
                    reason="stop",
                    message=AssistantMessage(
                        model="fake",
                        content=[TextContent(text="done")],
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
                tools=[],
                get_tools=get_tools,
            )
        )

        async for _ in harness.prompt("hello"):
            pass

        # turn 1 saw only A; turn 2 saw A and B
        self.assertEqual(provider.received_tools, [["A"], ["A", "B"]])
        self.assertTrue(state["b_active"])


class TestDynamicSystem(unittest.IsolatedAsyncioTestCase):
    async def test_get_system_reflects_per_turn_changes(self) -> None:
        # Turn 1 system is "normal"; after the tool executes, turn 2 system is "plan".
        systems = iter(["normal", "plan"])

        def get_system() -> str:
            return next(systems)

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
                        content=[TextContent(text="done")],
                        stop_reason="stop",
                    ),
                ),
            ]
        )

        harness = AgentHarness(
            AgentHarnessConfig(
                provider=provider,
                model="fake",
                system="static",  # fallback - must never be seen
                get_system=get_system,
                tools=[_tool_named("noop")],
            )
        )

        async for _ in harness.prompt("hello"):
            pass

        self.assertEqual(provider.received_systems, ["normal", "plan"])


class TestPrepareContextCopy(unittest.IsolatedAsyncioTestCase):
    async def test_prepare_context_does_not_mutate_durable_history(self) -> None:
        # prepare_context must return a new list; temporary injections must not
        # leak into the harness's durable messages.
        injected = UserMessage(content="INJECTED")
        seen_inputs: list[list] = []
        prepared_returns: list[list] = []

        def prepare_context(msgs):
            seen_inputs.append(msgs)
            prepared = [*msgs, injected]  # new list, does not mutate `msgs`
            prepared_returns.append(prepared)
            return prepared

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
                prepare_context=prepare_context,
            )
        )

        async for _ in harness.prompt("hello"):
            pass

        # prepare_context's output reached the provider (injection present)
        self.assertIs(provider.received_messages[0][-1], injected)
        # prepare_context returned a new list, not the durable message container
        self.assertIsNot(prepared_returns[0], harness.messages)
        # prepare_context received a filtered copy, not the durable list object
        self.assertIsNot(seen_inputs[0], harness.messages)
        # the injection did NOT leak into durable history
        self.assertNotIn("INJECTED", [getattr(m, "text", "") for m in harness.messages])


if __name__ == "__main__":
    unittest.main(verbosity=2)
