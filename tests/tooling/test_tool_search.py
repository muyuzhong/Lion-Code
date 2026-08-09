from __future__ import annotations

import json
import unittest
from pathlib import Path

from lion_code.core.cancellation import CancellationToken
from lion_code.permission_state import PermissionController, PermissionState
from lion_code.session_identity import SessionIdentityState
from lion_code.tooling.context import ToolContext
from lion_code.tooling.internal import (
    create_enter_plan_mode_tool,
    create_exit_plan_mode_tool,
    create_tool_search_tool,
)
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.runtime import ToolRuntime


class TestToolSearch(unittest.IsolatedAsyncioTestCase):
    def _runtime(self):
        registry = ToolRegistry()
        for tool in (
            create_enter_plan_mode_tool(),
            create_exit_plan_mode_tool(),
            create_tool_search_tool(),
        ):
            registry.register(tool)
        context = ToolContext(
            session=SessionIdentityState("session", "2026-08-09T00:00:00Z"),
            cancellation=CancellationToken(),
            cwd=Path.cwd(),
            controller=object(),
            registry=registry,
            permission=PermissionController(PermissionState("default")),
            plan_file_path=None,
            read_file_state={},
        )
        return registry, ToolRuntime(registry, context)

    async def test_tool_search_activates_matching_deferred_tool(self):
        registry, runtime = self._runtime()

        result = await runtime.execute(
            tool_call_id="call-1",
            name="tool_search",
            arguments={"query": "enter plan"},
        )

        self.assertEqual(result.activated_tools, ["enter_plan_mode"])
        self.assertTrue(registry.is_active("enter_plan_mode"))
        self.assertFalse(registry.is_active("exit_plan_mode"))
        schemas = json.loads(result.content)
        self.assertEqual([schema["name"] for schema in schemas], ["enter_plan_mode"])

    async def test_activation_is_local_to_registry(self):
        first, first_runtime = self._runtime()
        second, _ = self._runtime()

        await first_runtime.execute(
            tool_call_id="call-1",
            name="tool_search",
            arguments={"query": "plan mode"},
        )

        self.assertTrue(first.is_active("enter_plan_mode"))
        self.assertEqual(second.deferred_tool_names(), [
            "enter_plan_mode",
            "exit_plan_mode",
        ])


if __name__ == "__main__":
    unittest.main()
