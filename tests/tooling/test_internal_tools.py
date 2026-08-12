from __future__ import annotations

import unittest
from pathlib import Path

from core.fakes import FakePlanView

from lion_code.core.cancellation import CancellationToken
from lion_code.permission_state import PermissionController, PermissionState
from lion_code.session_identity import SessionIdentityState
from lion_code.tooling.context import ToolContext
from lion_code.tooling.internal import (
    create_agent_tool,
    create_enter_plan_tool,
    create_exit_plan_tool,
    create_skill_tool,
    create_wakeup_tool,
)
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.runtime import ToolRuntime
from lion_code.tooling.types import ToolResult


class _Command:
    def __init__(self, name, content):
        self.name = name
        self.content = content
        self.calls = []

    async def __call__(self, arguments):
        self.calls.append((self.name, dict(arguments)))
        return ToolResult(content=self.content)


def _runtime(tool):
    registry = ToolRegistry()
    registry.register(tool, activate=True)
    context = ToolContext(
        session=SessionIdentityState("session", "2026-08-09T00:00:00Z"),
        cancellation=CancellationToken(),
        cwd=Path.cwd(),
        registry=registry,
        permission=PermissionController(PermissionState("default")),
        plan=FakePlanView(),
        read_file_state={},
    )
    return ToolRuntime(registry, context)


class TestInternalTools(unittest.IsolatedAsyncioTestCase):
    async def test_agent_tool_calls_injected_command(self):
        command = _Command("agent", "agent result")
        runtime = _runtime(create_agent_tool(command))

        result = await runtime.execute(
            tool_call_id="call-1",
            name="agent",
            arguments={"prompt": "inspect", "description": "repo"},
        )

        self.assertEqual(result.content, "agent result")
        self.assertEqual(
            command.calls,
            [("agent", {"prompt": "inspect", "description": "repo"})],
        )

    async def test_skill_tool_calls_injected_command(self):
        command = _Command("skill", "skill result")
        runtime = _runtime(create_skill_tool(command))

        result = await runtime.execute(
            tool_call_id="call-1",
            name="skill",
            arguments={"skill_name": "demo"},
        )

        self.assertEqual(result.content, "skill result")
        self.assertEqual(command.calls, [("skill", {"skill_name": "demo"})])

    async def test_plan_tools_call_distinct_injected_commands(self):
        enter_command = _Command("enter", "entered")
        exit_command = _Command("exit", "exited")
        for tool, expected in (
            (create_enter_plan_tool(enter_command), "enter"),
            (create_exit_plan_tool(exit_command), "exit"),
        ):
            runtime = _runtime(tool)

            result = await runtime.execute(
                tool_call_id="call-1",
                name=tool.name,
                arguments={},
            )

            self.assertEqual(result.content, f"{expected}ed")
            command = enter_command if expected == "enter" else exit_command
            self.assertEqual(command.calls, [(expected, {})])

    async def test_wakeup_tool_calls_injected_command(self):
        command = _Command("wakeup", "scheduled")
        runtime = _runtime(create_wakeup_tool(command))
        arguments = {"delaySeconds": 60, "reason": "later", "prompt": "work"}

        result = await runtime.execute(
            tool_call_id="call-1",
            name="schedule_wakeup",
            arguments=arguments,
        )

        self.assertEqual(result.content, "scheduled")
        self.assertEqual(command.calls, [("wakeup", arguments)])


if __name__ == "__main__":
    unittest.main()
