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
    ToolExecutionEndEvent,
    ToolExecutionUpdateEvent,
    TurnEndEvent,
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

    async def test_all_terminating_tool_results_skip_provider_follow_up(self) -> None:
        async def execute(tool_call_id, arguments, signal, on_update):
            return AgentToolResult(
                content=[TextContent(text=tool_call_id)],
                terminate=True,
            )

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
                    ),
                )
            ]
        )
        tools = [
            AgentTool(
                name=name,
                label=name,
                description=name,
                parameters={},
                execute_fn=execute,
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

        async for _ in harness.prompt("hello"):
            pass

        self.assertEqual(provider.call_count, 1)
        self.assertEqual(
            [message.role for message in harness.messages],
            ["user", "assistant", "toolResult", "toolResult"],
        )

    async def test_mixed_terminate_results_keep_provider_follow_up(self) -> None:
        async def execute(tool_call_id, arguments, signal, on_update):
            return AgentToolResult(
                content=[TextContent(text=tool_call_id)],
                terminate=tool_call_id == "c1",
            )

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
                    ),
                ),
                AssistantDoneEvent(
                    reason="stop",
                    message=AssistantMessage(
                        model="fake",
                        content=[TextContent(text="final")],
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

        async for _ in harness.prompt("hello"):
            pass

        self.assertEqual(provider.call_count, 2)
        self.assertEqual(harness.messages[-1].text, "final")

    async def test_prepare_arguments_runs_before_hooks_and_execute(self) -> None:
        observed: list[tuple[str, dict]] = []

        def prepare(arguments):
            observed.append(("prepare", dict(arguments)))
            return {"msg": arguments["legacy"]}

        async def before(call):
            observed.append(("before", dict(call.arguments)))
            return False, None

        async def execute(tool_call_id, arguments, signal, on_update):
            observed.append(("execute", dict(arguments)))
            return AgentToolResult(content=[TextContent(text=arguments["msg"])])

        provider = FakeProvider(
            [
                AssistantDoneEvent(
                    reason="toolUse",
                    message=AssistantMessage(
                        model="fake",
                        content=[
                            ToolCall(
                                id="c1",
                                name="compat",
                                arguments={"legacy": "converted"},
                            )
                        ],
                    ),
                ),
                AssistantDoneEvent(
                    reason="stop",
                    message=AssistantMessage(
                        model="fake",
                        content=[TextContent(text="final")],
                    ),
                ),
            ]
        )
        harness = AgentHarness(
            AgentHarnessConfig(
                provider=provider,
                model="fake",
                system="test",
                tools=[
                    AgentTool(
                        name="compat",
                        label="Compat",
                        description="compat",
                        parameters={},
                        execute_fn=execute,
                        prepare_arguments=prepare,
                    )
                ],
                before_tool_call=before,
            )
        )

        async for _ in harness.prompt("hello"):
            pass

        self.assertEqual(
            observed,
            [
                ("prepare", {"legacy": "converted"}),
                ("before", {"msg": "converted"}),
                ("execute", {"msg": "converted"}),
            ],
        )

    async def test_tool_updates_are_emitted_before_execution_finishes(self) -> None:
        release = asyncio.Event()

        async def execute(tool_call_id, arguments, signal, on_update):
            on_update(AgentToolResult(content=[TextContent(text="working")]))
            await release.wait()
            return AgentToolResult(content=[TextContent(text="done")])

        provider = FakeProvider(
            [
                AssistantDoneEvent(
                    reason="toolUse",
                    message=AssistantMessage(
                        model="fake",
                        content=[ToolCall(id="c1", name="slow", arguments={})],
                    ),
                ),
                AssistantDoneEvent(
                    reason="stop",
                    message=AssistantMessage(
                        model="fake",
                        content=[TextContent(text="final")],
                    ),
                ),
            ]
        )
        harness = AgentHarness(
            AgentHarnessConfig(
                provider=provider,
                model="fake",
                system="test",
                tools=[
                    AgentTool(
                        name="slow",
                        label="Slow",
                        description="slow",
                        parameters={},
                        execute_fn=execute,
                    )
                ],
            )
        )
        events = []

        async def consume() -> None:
            async for event in harness.prompt("hello"):
                events.append(event)
                if isinstance(event, ToolExecutionUpdateEvent):
                    release.set()

        await asyncio.wait_for(consume(), timeout=1)

        update_index = next(
            index
            for index, event in enumerate(events)
            if isinstance(event, ToolExecutionUpdateEvent)
        )
        end_index = next(
            index
            for index, event in enumerate(events)
            if isinstance(event, ToolExecutionEndEvent)
        )
        self.assertLess(update_index, end_index)

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


class TestStructuredToolError(unittest.IsolatedAsyncioTestCase):
    async def test_tool_returning_is_error_is_not_reclassified_as_success(self) -> None:
        # A tool that surfaces a structured error (e.g. a host runtime denial)
        # without raising must propagate is_error=True to the tool result
        # message, not be silently marked successful.
        async def execute(tool_call_id, arguments, signal, on_update):
            return AgentToolResult(
                content=[TextContent(text="denied by policy")],
                details={},
                is_error=True,
            )

        provider = FakeProvider(
            [
                AssistantDoneEvent(
                    reason="toolUse",
                    message=AssistantMessage(
                        model="fake",
                        content=[ToolCall(id="c1", name="guarded", arguments={})],
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
                tools=[
                    AgentTool(
                        name="guarded",
                        label="Guarded",
                        description="guarded",
                        parameters={},
                        execute_fn=execute,
                    )
                ],
            )
        )

        async for _ in harness.prompt("hello"):
            pass

        messages = harness.messages
        self.assertTrue(messages[2].is_error)
        self.assertEqual(messages[2].text, "denied by policy")



class TestAgentEndTerminalPaths(unittest.IsolatedAsyncioTestCase):
    async def test_max_turns_zero_emits_agent_end(self) -> None:
        harness = AgentHarness(
            AgentHarnessConfig(
                provider=FakeProvider([]),
                model="fake",
                system="test",
                max_turns=0,
            )
        )

        events = [event async for event in harness.prompt("hello")]

        self.assertEqual(
            sum(isinstance(event, AgentEndEvent) for event in events), 1
        )

    async def test_max_turns_exceeded_after_steering_emits_agent_end(self) -> None:
        async def execute(tool_call_id, arguments, signal, on_update):
            return AgentToolResult(
                content=[TextContent(text="ok")],
                details={},
            )

        provider = FakeProvider(
            [
                AssistantDoneEvent(
                    reason="toolUse",
                    message=AssistantMessage(
                        model="fake",
                        content=[ToolCall(id="c1", name="echo", arguments={})],
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
                tools=[
                    AgentTool(
                        name="echo",
                        label="Echo",
                        description="echo",
                        parameters={},
                        execute_fn=execute,
                    )
                ],
                max_turns=1,
            )
        )

        events: list = []
        first_turn_end = False
        async for event in harness.prompt("hello"):
            events.append(event)
            if isinstance(event, TurnEndEvent) and not first_turn_end:
                first_turn_end = True
                harness.steer("next")

        self.assertEqual(
            sum(isinstance(event, AgentEndEvent) for event in events), 1
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
