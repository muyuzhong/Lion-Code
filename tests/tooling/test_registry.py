from __future__ import annotations

import unittest

from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.types import LionTool, ToolCapabilities, ToolResult


async def _execute(_context, _tool_call_id, _arguments, _on_update):
    return ToolResult(content="ok")


def _tool(name: str, *, deferred: bool = False) -> LionTool:
    return LionTool(
        name=name,
        label=name,
        description=f"{name} description",
        parameters={"type": "object", "properties": {}},
        execute_fn=_execute,
        capabilities=ToolCapabilities(deferred=deferred),
    )


class TestToolRegistry(unittest.TestCase):
    def test_register_and_resolve_tool(self):
        registry = ToolRegistry()
        tool = _tool("read_file")

        registry.register(tool)

        self.assertIs(registry.resolve("read_file"), tool)
        self.assertEqual(registry.active_tools(), [tool])

    def test_duplicate_tool_rejected(self):
        registry = ToolRegistry()
        registry.register(_tool("read_file"))

        with self.assertRaisesRegex(ValueError, "Duplicate tool: read_file"):
            registry.register(_tool("read_file"))

    def test_deferred_tool_not_active(self):
        registry = ToolRegistry()
        tool = _tool("enter_plan_mode", deferred=True)

        registry.register(tool)

        self.assertEqual(registry.active_tools(), [])
        self.assertIs(registry.activate(tool.name), tool)
        self.assertEqual(registry.active_tools(), [tool])

    def test_registry_state_is_agent_local(self):
        first = ToolRegistry()
        second = ToolRegistry()
        first.register(_tool("deferred", deferred=True))
        second.register(_tool("deferred", deferred=True))

        first.activate("deferred")

        self.assertEqual([tool.name for tool in first.active_tools()], ["deferred"])
        self.assertEqual(second.active_tools(), [])

    def test_unknown_tool_raises_lookup_error(self):
        with self.assertRaisesRegex(LookupError, "Unknown tool: missing"):
            ToolRegistry().resolve("missing")


if __name__ == "__main__":
    unittest.main()
