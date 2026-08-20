from __future__ import annotations

import inspect
import unittest
from unittest.mock import AsyncMock, patch

from full_agent import FullAgentHarness, build_full_agent_harness, execute_tool

from lion_code.tooling.types import ToolResult


class TestAgentInternalRuntime(unittest.IsolatedAsyncioTestCase):
    def _agent(self) -> FullAgentHarness:
        with patch("full_agent.load_pre_tool_use_hooks", return_value=[]):
            return build_full_agent_harness(api_key="test-key")

    async def test_internal_tool_uses_bound_executor(self):
        agent = self._agent()
        agent.composition.capabilities.subagent_executor.execute = AsyncMock(
            return_value=ToolResult(content="sub-agent result")
        )

        result = await execute_tool(
            agent,
            "agent",
            {"description": "inspect", "prompt": "inspect the repo"},
            "call-1",
        )

        self.assertEqual(result, "sub-agent result")
        agent.composition.capabilities.subagent_executor.execute.assert_awaited_once_with(
            agent_type="general",
            description="inspect",
            prompt="inspect the repo",
        )

    async def test_tool_search_updates_model_schema_from_registry(self):
        agent = self._agent()
        before = {
            tool.name
            for tool in agent.composition.runtime.conversation.harness.config.get_tools()
        }

        result = await execute_tool(agent, "tool_search", {"query": "enter plan"})
        after = {
            tool.name
            for tool in agent.composition.runtime.conversation.harness.config.get_tools()
        }

        self.assertNotIn("enter_plan_mode", before)
        self.assertIn("enter_plan_mode", after)
        self.assertIn('"name": "enter_plan_mode"', result)

    def test_tool_runtime_router_contains_no_tool_name_branches(self):
        from lion_code.tooling.runtime import ToolRuntime

        source = inspect.getsource(ToolRuntime.execute)

        for forbidden in (
            'name == "agent"',
            'name == "skill"',
            'name in ("enter_plan_mode", "exit_plan_mode")',
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
