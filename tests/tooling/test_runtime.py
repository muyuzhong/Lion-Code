from __future__ import annotations

import unittest

from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.runtime import ToolRuntime
from lion_code.tooling.types import LionTool, ToolResult


def _tool(name, execute_fn):
    return LionTool(
        name=name,
        label=name,
        description=name,
        parameters={"type": "object", "properties": {}},
        execute_fn=execute_fn,
    )


class TestToolRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_executes_registered_tool(self):
        async def execute(tool_call_id, arguments):
            return ToolResult(content=f"{tool_call_id}:{arguments['value']}")

        registry = ToolRegistry()
        registry.register(_tool("echo", execute))

        result = await ToolRuntime(registry).execute(
            tool_call_id="call-1",
            name="echo",
            arguments={"value": "hello"},
        )

        self.assertFalse(result.is_error)
        self.assertEqual(result.content, "call-1:hello")

    async def test_unknown_tool_is_error_result(self):
        result = await ToolRuntime(ToolRegistry()).execute(
            tool_call_id="call-1",
            name="missing",
            arguments={},
        )

        self.assertTrue(result.is_error)
        self.assertEqual(result.content, "Unknown tool: missing")

    async def test_runtime_converts_exception_to_error_result(self):
        async def execute(_tool_call_id, _arguments):
            raise RuntimeError("boom")

        registry = ToolRegistry()
        registry.register(_tool("explode", execute))

        result = await ToolRuntime(registry).execute(
            tool_call_id="call-1",
            name="explode",
            arguments={},
        )

        self.assertTrue(result.is_error)
        self.assertEqual(result.content, "RuntimeError: boom")


if __name__ == "__main__":
    unittest.main()
