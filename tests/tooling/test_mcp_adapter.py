from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from lion_code.agent import Agent
from lion_code.core.cancellation import CancellationToken
from lion_code.mcp_client import DiscoveredMcpTool, McpManager
from lion_code.permission_state import PermissionController, PermissionState
from lion_code.session_identity import SessionIdentityState
from lion_code.tooling.context import ToolContext
from lion_code.tooling.environment import ToolEnvironment
from lion_code.tooling.mcp import create_mcp_tool
from lion_code.tooling.middleware import PermissionMiddleware
from lion_code.tooling.permission import PermissionPolicy
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.runtime import ToolRuntime


class _Manager:
    def __init__(self):
        self.call_remote_tool = AsyncMock(return_value="remote result")


def _definition() -> DiscoveredMcpTool:
    return DiscoveredMcpTool(
        server_name="docs",
        remote_name="search__pages",
        description="Search pages",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
    )


def _context(registry, *, confirm_fn=None, permission=None):
    return ToolContext(
        session=SessionIdentityState("session", "2026-08-09T00:00:00Z"),
        cancellation=CancellationToken(),
        cwd=Path.cwd(),
        controller=object(),
        registry=registry,
        permission=permission or PermissionController(PermissionState("default")),
        plan_file_path=None,
        read_file_state={},
        confirm_fn=confirm_fn,
    )


class TestMcpAdapter(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_tool_uses_runtime_pipeline(self):
        manager = _Manager()
        tool = create_mcp_tool(manager, _definition())
        registry = ToolRegistry()
        registry.register(tool)
        events = []

        class Middleware:
            phase = "pre"

            async def handle(self, *, call_next, **_):
                events.append("middleware")
                return await call_next()

        runtime = ToolRuntime(
            registry,
            _context(registry),
            [Middleware()],
        )

        result = await runtime.execute(
            tool_call_id="call-1",
            name="mcp__docs__search__pages",
            arguments={"query": "runtime"},
        )

        self.assertEqual(events, ["middleware"])
        self.assertEqual(result.content, "remote result")
        self.assertEqual(result.details["source"], "mcp")
        manager.call_remote_tool.assert_awaited_once_with(
            server_name="docs",
            tool_name="search__pages",
            arguments={"query": "runtime"},
        )

    async def test_mcp_tool_blocked_by_permission(self):
        manager = _Manager()
        tool = create_mcp_tool(manager, _definition())
        registry = ToolRegistry()
        registry.register(tool)
        permission = PermissionController(PermissionState("default"))
        runtime = ToolRuntime(
            registry,
            _context(registry, permission=permission),
            [PermissionMiddleware(PermissionPolicy(), permission)],
        )

        result = await runtime.execute(
            tool_call_id="call-1",
            name=tool.name,
            arguments={"query": "blocked"},
        )

        self.assertTrue(result.is_error)
        manager.call_remote_tool.assert_not_awaited()

    def test_adapter_uses_conservative_capabilities(self):
        tool = create_mcp_tool(_Manager(), _definition())

        self.assertFalse(tool.capabilities.read_only)
        self.assertFalse(tool.capabilities.concurrency_safe)
        self.assertTrue(tool.capabilities.external_side_effect)
        self.assertTrue(tool.capabilities.requires_confirmation)

    def test_agent_has_no_mcp_prefix_router(self):
        source = inspect.getsource(Agent._execute_tool_call)

        self.assertNotIn("mcp__", source)
        self.assertFalse(hasattr(McpManager, "is_mcp_tool"))

    async def test_root_agent_registers_discovered_tools_and_closes_once(self):
        manager = _Manager()
        manager.discover_tools = AsyncMock(return_value=[_definition()])
        manager.disconnect_all = AsyncMock()
        environment = ToolEnvironment(mcp_manager=manager)
        with patch("lion_code.agent.load_pre_tool_use_hooks", return_value=[]):
            agent = Agent(
                api_key="test-key",
                tool_environment=environment,
            )
        agent._ensure_core_session_ready = AsyncMock()
        agent.core_runtime.prompt = AsyncMock()

        await agent.chat("first")
        await agent.chat("second")
        await agent.close()
        await agent.close()

        manager.discover_tools.assert_awaited_once_with()
        self.assertEqual(agent.core_runtime.prompt.await_count, 2)
        self.assertEqual(
            agent.tool_registry.resolve("mcp__docs__search__pages").label,
            "search__pages",
        )
        manager.disconnect_all.assert_awaited_once_with()


if __name__ == "__main__":
    unittest.main()
