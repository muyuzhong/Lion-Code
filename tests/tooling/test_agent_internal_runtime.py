from __future__ import annotations

import inspect
import unittest
from unittest.mock import AsyncMock, patch

from lion_code.agent import Agent
from lion_code.tooling.types import ToolResult


class TestAgentInternalRuntime(unittest.IsolatedAsyncioTestCase):
    def _agent(self):
        with patch("lion_code.agent.load_pre_tool_use_hooks", return_value=[]):
            return Agent(api_key="test-key")

    async def test_internal_tool_uses_bound_executor(self):
        agent = self._agent()
        agent._subagent_executor.execute = AsyncMock(
            return_value=ToolResult(content="sub-agent result")
        )

        result = await agent._execute_tool_call(
            "agent",
            {"description": "inspect", "prompt": "inspect the repo"},
            "call-1",
        )

        self.assertEqual(result, "sub-agent result")
        agent._subagent_executor.execute.assert_awaited_once_with(
            agent_type="general",
            description="inspect",
            prompt="inspect the repo",
        )

    async def test_tool_search_updates_model_schema_from_registry(self):
        agent = self._agent()
        before = {tool.name for tool in agent.core_runtime.harness.config.get_tools()}

        result = await agent._execute_tool_call(
            "tool_search",
            {"query": "enter plan"},
        )
        after = {tool.name for tool in agent.core_runtime.harness.config.get_tools()}

        self.assertNotIn("enter_plan_mode", before)
        self.assertIn("enter_plan_mode", after)
        self.assertIn('"name": "enter_plan_mode"', result)

    def test_agent_router_contains_no_tool_name_branches(self):
        source = inspect.getsource(Agent._execute_tool_call)

        for forbidden in (
            'name == "agent"',
            'name == "skill"',
            'name in ("enter_plan_mode", "exit_plan_mode")',
            "run_pre_tool_use_hooks",
            "check_permission",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
