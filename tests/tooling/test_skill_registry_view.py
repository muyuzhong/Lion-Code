from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from lion_code.agent import Agent
from lion_code.tooling.types import LionTool, ToolResult


async def _execute(_context, _tool_call_id, _arguments, _on_update):
    return ToolResult(content="ok")


def _tool(name: str) -> LionTool:
    return LionTool(
        name=name,
        label=name,
        description=name,
        parameters={"type": "object", "properties": {}},
        execute_fn=_execute,
    )


class _ChildAgent:
    created_with = None
    last_instance = None

    def __init__(self, **kwargs):
        type(self).created_with = kwargs
        type(self).last_instance = self
        self.run_once = AsyncMock(
            return_value={
                "text": "skill result",
                "tokens": {"input": 1, "output": 2},
            }
        )
        self.close = AsyncMock()


class TestSkillRegistryView(unittest.IsolatedAsyncioTestCase):
    def test_factory_import_defers_agent_module(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import lion_code.subagent_factory; "
                "assert 'lion_code.agent' not in sys.modules",
            ],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    async def test_subagent_uses_parent_registry_view_and_shared_environment(self):
        with patch("lion_code.agent.load_pre_tool_use_hooks", return_value=[]):
            parent = Agent(api_key="test-key")
        mcp_name = "mcp__docs__search"
        parent.tool_registry.register(_tool(mcp_name))

        with (
            patch("lion_code.agent.Agent", _ChildAgent),
            patch("lion_code.agent.print_sub_agent_start"),
            patch("lion_code.agent.print_sub_agent_end"),
        ):
            result = await parent._execute_agent_tool(
                {
                    "type": "general",
                    "description": "research",
                    "prompt": "find docs",
                }
            )

        kwargs = _ChildAgent.created_with
        child_registry = kwargs["tool_registry"]
        self.assertEqual(result, "skill result")
        self.assertIs(child_registry.resolve(mcp_name), parent.tool_registry.resolve(mcp_name))
        with self.assertRaises(LookupError):
            child_registry.resolve("agent")
        self.assertIs(
            kwargs["tool_environment"].mcp_manager,
            parent.tool_environment.mcp_manager,
        )
        _ChildAgent.last_instance.close.assert_awaited_once_with()

    async def test_subagent_inherits_current_api_configuration_and_auto_mode(self):
        with patch("lion_code.agent.load_pre_tool_use_hooks", return_value=[]):
            parent = Agent(
                api_base="https://example.test/v1",
                api_key="test-key",
                permission_mode="auto",
            )

        with (
            patch("lion_code.agent.Agent", _ChildAgent),
            patch("lion_code.agent.print_sub_agent_start"),
            patch("lion_code.agent.print_sub_agent_end"),
        ):
            await parent._execute_agent_tool(
                {
                    "type": "general",
                    "description": "research",
                    "prompt": "find docs",
                }
            )

        self.assertEqual(
            _ChildAgent.created_with["api_base"],
            "https://example.test/v1",
        )
        self.assertEqual(_ChildAgent.created_with["api_key"], "test-key")
        self.assertEqual(_ChildAgent.created_with["permission_mode"], "auto")
        self.assertTrue(_ChildAgent.created_with["is_sub_agent"])

    async def test_fork_paths_read_api_and_permission_at_construction_time(self):
        with patch("lion_code.agent.load_pre_tool_use_hooks", return_value=[]):
            parent = Agent(
                api_base="https://old.example.test/v1",
                api_key="old-key",
            )
        parent.configure_api(
            model="current-model",
            api_base="https://new.example.test/v1",
            api_key="new-key",
        )
        parent._permission_controller.set_mode("auto")
        skill_result = {
            "context": "fork",
            "allowed_tools": ["read_file"],
            "prompt": "Read the requested file.",
        }

        with (
            patch("lion_code.agent.Agent", _ChildAgent),
            patch("lion_code.skills.execute_skill", return_value=skill_result),
            patch("lion_code.agent.print_sub_agent_start"),
            patch("lion_code.agent.print_sub_agent_end"),
        ):
            await parent._execute_agent_tool(
                {
                    "type": "general",
                    "description": "research",
                    "prompt": "find docs",
                }
            )
            agent_kwargs = dict(_ChildAgent.created_with)

            parent._permission_controller.set_mode("plan")
            await parent._execute_skill_tool(
                {"skill_name": "research", "args": "find docs"}
            )
            skill_kwargs = dict(_ChildAgent.created_with)

        for kwargs in (agent_kwargs, skill_kwargs):
            self.assertEqual(kwargs["model"], "current-model")
            self.assertEqual(kwargs["api_base"], "https://new.example.test/v1")
            self.assertEqual(kwargs["api_key"], "new-key")
        self.assertEqual(agent_kwargs["permission_mode"], "auto")
        self.assertEqual(skill_kwargs["permission_mode"], "plan")

    async def test_permission_mode_is_a_read_only_facade(self):
        with patch("lion_code.agent.load_pre_tool_use_hooks", return_value=[]):
            parent = Agent(api_key="test-key", permission_mode="auto")

        with self.assertRaises(AttributeError):
            setattr(parent, "permission_mode", "plan")

        self.assertEqual(parent.permission_mode, "auto")

    async def test_agent_tool_error_emits_end_before_closing_without_charging_usage(self):
        with patch("lion_code.agent.load_pre_tool_use_hooks", return_value=[]):
            parent = Agent(api_key="test-key")
        events: list[object] = []
        child = _ChildAgent()
        child.run_once.side_effect = RuntimeError("boom")

        async def close_child():
            events.append("close")

        child.close.side_effect = close_child

        def record_status(_agent_type, _description, *, started):
            events.append(("status", started))

        with (
            patch.object(
                parent._subagent_factory,
                "create_for_agent_type",
                return_value=child,
            ),
            patch.object(parent, "_emit_subagent_status", side_effect=record_status),
        ):
            result = await parent._execute_agent_tool(
                {
                    "type": "general",
                    "description": "research",
                    "prompt": "find docs",
                }
            )

        self.assertEqual(result, "Sub-agent error: boom")
        self.assertEqual(parent.get_token_usage(), {"input": 0, "output": 0})
        self.assertEqual(
            events,
            [("status", True), ("status", False), "close"],
        )
        child.close.assert_awaited_once_with()

    async def test_fork_skill_selects_parent_registry_including_mcp(self):
        with patch("lion_code.agent.load_pre_tool_use_hooks", return_value=[]):
            parent = Agent(api_key="test-key")
        mcp_name = "mcp__docs__search"
        mcp_tool = _tool(mcp_name)
        parent.tool_registry.register(mcp_tool)
        skill_result = {
            "context": "fork",
            "allowed_tools": [mcp_name],
            "prompt": "Use the MCP search tool.",
        }

        with (
            patch("lion_code.skills.execute_skill", return_value=skill_result),
            patch("lion_code.agent.Agent", _ChildAgent),
            patch("lion_code.agent.print_sub_agent_start"),
            patch("lion_code.agent.print_sub_agent_end"),
        ):
            result = await parent._execute_skill_tool(
                {"skill_name": "research", "args": "find docs"}
            )

        kwargs = _ChildAgent.created_with
        child_registry = kwargs["tool_registry"]
        self.assertEqual(result, "skill result")
        self.assertEqual(
            [tool.name for tool in child_registry.all_tools()],
            [mcp_name],
        )
        self.assertIs(child_registry.resolve(mcp_name), mcp_tool)
        self.assertIs(
            kwargs["tool_environment"].mcp_manager,
            parent.tool_environment.mcp_manager,
        )
        self.assertFalse(kwargs["tool_environment"].owns_mcp_manager)
        _ChildAgent.last_instance.close.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()
