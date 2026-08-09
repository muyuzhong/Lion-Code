from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from lion_code.agent import Agent
from lion_code.session_memory import SessionMemoryRepository
from lion_code.session_runtime import SessionRepository
from lion_code.tooling.types import ToolResult


class TestAgentBuiltinRuntime(unittest.IsolatedAsyncioTestCase):
    def _agent(self, **kwargs):
        with patch("lion_code.agent.load_pre_tool_use_hooks", return_value=[]):
            return Agent(api_key="test-key", **kwargs)

    async def test_builtin_call_uses_runtime(self):
        agent = self._agent()
        agent.tool_runtime.execute = AsyncMock(
            return_value=ToolResult(content="through runtime")
        )

        result = await agent._execute_tool_call(
            "read_file",
            {"file_path": "README.md"},
            "call-1",
        )

        self.assertEqual(result, "through runtime")
        agent.tool_runtime.execute.assert_awaited_once_with(
            tool_call_id="call-1",
            name="read_file",
            arguments={"file_path": "README.md"},
        )

    async def test_runtime_preserves_read_before_write_state(self):
        agent = self._agent(permission_mode="bypassPermissions")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.txt"
            path.write_text("before", encoding="utf-8")

            denied = await agent._execute_tool_call(
                "write_file",
                {"file_path": str(path), "content": "after"},
            )
            await agent._execute_tool_call(
                "read_file",
                {"file_path": str(path)},
            )
            allowed = await agent._execute_tool_call(
                "write_file",
                {"file_path": str(path), "content": "after"},
            )

        self.assertIn("must read this file", denied)
        self.assertIn("Successfully wrote", allowed)

    async def test_toggle_plan_mode_preserves_live_permission_view(self):
        agent = self._agent(permission_mode="acceptEdits", terminal_output=False)
        permission = agent.tool_context.permission

        with patch.object(
            agent,
            "_generate_plan_file_path",
            return_value="plan.md",
        ):
            self.assertEqual(agent.toggle_plan_mode(), "plan")
            self.assertIs(agent.tool_context.permission, permission)
            self.assertEqual(permission.mode, "plan")

            self.assertEqual(agent.toggle_plan_mode(), "acceptEdits")
            self.assertIs(agent.tool_context.permission, permission)
            self.assertEqual(permission.mode, "acceptEdits")

        await agent.close()

    async def test_plan_tools_preserve_live_permission_view(self):
        agent = self._agent(permission_mode="auto", terminal_output=False)
        permission = agent.tool_context.permission

        with patch.object(
            agent,
            "_generate_plan_file_path",
            return_value="plan.md",
        ):
            await agent._execute_plan_mode_tool("enter_plan_mode")
            self.assertIs(agent.tool_context.permission, permission)
            self.assertEqual(permission.mode, "plan")

            await agent._execute_plan_mode_tool("exit_plan_mode")
            self.assertIs(agent.tool_context.permission, permission)
            self.assertEqual(permission.mode, "auto")

        await agent.close()

    async def test_clear_in_plan_mode_preserves_live_permission_view(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            session_repository = SessionRepository(root / "sessions")
            memory_repository = SessionMemoryRepository(storage_dir=root / "memory")
            with patch(
                "lion_code.agent.Agent._generate_plan_file_path",
                return_value=str(root / "plan.md"),
            ) as generate_plan_file_path:
                agent = self._agent(
                    permission_mode="plan",
                    session_repository=session_repository,
                    session_memory_repository=memory_repository,
                    terminal_output=False,
                )
                permission = agent.tool_context.permission

                await agent.clear_history()

            self.assertEqual(generate_plan_file_path.call_count, 2)
            self.assertIs(agent.tool_context.permission, permission)
            self.assertEqual(permission.mode, "plan")
            self.assertEqual(agent.tool_context.plan_file_path, str(root / "plan.md"))
            await agent.close()

    def test_model_schema_comes_from_agent_registry(self):
        agent = self._agent()
        read_tool = agent.tool_registry.resolve("read_file")
        core_tools = {
            tool.name: tool
            for tool in agent.core_runtime.harness.config.get_tools()
        }
        schema = read_tool.to_anthropic_schema()

        self.assertEqual(core_tools["read_file"].description, schema["description"])
        self.assertEqual(dict(core_tools["read_file"].parameters), schema["input_schema"])

    def test_custom_tools_limit_registry(self):
        agent = self._agent(
            custom_tools=[
                {
                    "name": "read_file",
                    "description": "compat",
                    "input_schema": {"type": "object", "properties": {}},
                }
            ]
        )

        self.assertEqual(
            [tool.name for tool in agent.tool_registry.active_tools()],
            ["read_file"],
        )
        self.assertEqual(
            [tool.name for tool in agent.core_runtime.harness.config.get_tools()],
            ["read_file"],
        )

    def test_context_snipping_uses_registry_result_policy(self):
        agent = self._agent()

        self.assertTrue(agent._is_snippable_tool("read_file"))
        self.assertTrue(agent._is_snippable_tool("run_shell"))
        self.assertFalse(agent._is_snippable_tool("web_fetch"))
        self.assertFalse(agent._is_snippable_tool("missing"))


if __name__ == "__main__":
    unittest.main()
