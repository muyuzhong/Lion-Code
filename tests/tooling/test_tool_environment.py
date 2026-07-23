from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from lion_code.agent import Agent
from lion_code.tooling.environment import ToolEnvironment


class _Manager:
    def __init__(self):
        self.disconnect_all = AsyncMock()


class TestToolEnvironment(unittest.IsolatedAsyncioTestCase):
    def test_child_reuses_parent_mcp_manager(self):
        manager = _Manager()
        root = ToolEnvironment(mcp_manager=manager)

        child = root.child_view()

        self.assertIs(child.mcp_manager, manager)
        self.assertTrue(root.owns_mcp_manager)
        self.assertFalse(child.owns_mcp_manager)

    async def test_child_close_does_not_disconnect_mcp(self):
        manager = _Manager()
        child = ToolEnvironment(mcp_manager=manager).child_view()

        await child.close()

        manager.disconnect_all.assert_not_awaited()

    async def test_root_close_disconnects_mcp_once(self):
        manager = _Manager()
        root = ToolEnvironment(mcp_manager=manager)

        await root.close()
        await root.close()

        manager.disconnect_all.assert_awaited_once_with()

    async def test_standalone_subagent_does_not_own_default_manager(self):
        with patch("lion_code.agent.load_pre_tool_use_hooks", return_value=[]):
            child = Agent(api_key="test-key", is_sub_agent=True)
        child.tool_environment.mcp_manager.disconnect_all = AsyncMock()

        await child.close()

        self.assertFalse(child.tool_environment.owns_mcp_manager)
        child.tool_environment.mcp_manager.disconnect_all.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
