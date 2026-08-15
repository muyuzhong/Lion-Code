from __future__ import annotations

import unittest
from pathlib import Path


from lion_code.core.cancellation import CancellationToken
from lion_code.permission_state import PermissionController, PermissionState
from lion_code.session_identity import SessionIdentityState
from lion_code.tooling.context import ToolContext
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.runtime import ToolRuntime
from lion_code.tooling.types import LionTool, ToolResult


class _Controller:
    pass


def _context(registry):
    return ToolContext(
        session=SessionIdentityState("session", "2026-08-09T00:00:00Z"),
        cancellation=CancellationToken(),
        cwd=Path.cwd(),
        registry=registry,
        permission=PermissionController(PermissionState("default")),
        read_file_state={},
    )


def _tool(name, execute_fn):
    return LionTool(
        name=name,
        label=name,
        description=name,
        parameters={"type": "object", "properties": {}},
        execute_fn=execute_fn,
    )


class TestToolRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_context_reads_session_identity_dynamically(self):
        registry = ToolRegistry()
        session = SessionIdentityState("first", "2026-08-09T00:00:00Z")
        context = ToolContext(
            session=session,
            cancellation=CancellationToken(),
            cwd=Path.cwd(),
            registry=registry,
            permission=PermissionController(PermissionState("default")),
            read_file_state={},
        )

        session.reset("second", "2026-08-09T01:00:00Z")

        self.assertEqual(context.session.id, "second")
        self.assertEqual(context.session.started_at, "2026-08-09T01:00:00Z")

    async def test_matching_cancellation_view_reuses_original_context(self):
        seen_contexts = []

        async def execute(context, _tool_call_id, _arguments, _on_update):
            seen_contexts.append(context)
            return ToolResult(content="ok")

        registry = ToolRegistry()
        registry.register(_tool("capture", execute))
        context = _context(registry)
        runtime = ToolRuntime(registry, context)

        await runtime.execute(
            tool_call_id="call-1",
            name="capture",
            arguments={},
            cancellation=context.cancellation,
        )

        self.assertEqual(seen_contexts, [context])

    async def test_executes_registered_tool(self):
        async def execute(_context, tool_call_id, arguments, _on_update):
            return ToolResult(content=f"{tool_call_id}:{arguments['value']}")

        registry = ToolRegistry()
        registry.register(_tool("echo", execute))

        result = await ToolRuntime(registry, _context(registry)).execute(
            tool_call_id="call-1",
            name="echo",
            arguments={"value": "hello"},
        )

        self.assertFalse(result.is_error)
        self.assertEqual(result.content, "call-1:hello")

    async def test_unknown_tool_is_error_result(self):
        registry = ToolRegistry()
        result = await ToolRuntime(registry, _context(registry)).execute(
            tool_call_id="call-1",
            name="missing",
            arguments={},
        )

        self.assertTrue(result.is_error)
        self.assertEqual(result.content, "Unknown tool: missing")

    async def test_runtime_converts_exception_to_error_result(self):
        async def execute(_context, _tool_call_id, _arguments, _on_update):
            raise RuntimeError("boom")

        registry = ToolRegistry()
        registry.register(_tool("explode", execute))

        result = await ToolRuntime(registry, _context(registry)).execute(
            tool_call_id="call-1",
            name="explode",
            arguments={},
        )

        self.assertTrue(result.is_error)
        self.assertEqual(result.content, "RuntimeError: boom")

    async def test_pre_and_post_middleware_follow_declared_order(self):
        events = []

        class Middleware:
            def __init__(self, name, phase):
                self.name = name
                self.phase = phase

            async def handle(self, *, call_next, **_):
                events.append(self.name)
                return await call_next()

        async def execute(_context, _tool_call_id, _arguments, _on_update):
            events.append("tool")
            return ToolResult(content="ok")

        registry = ToolRegistry()
        registry.register(_tool("ordered", execute))
        runtime = ToolRuntime(
            registry,
            _context(registry),
            [
                Middleware("cancellation", "pre"),
                Middleware("hook", "pre"),
                Middleware("permission", "pre"),
                Middleware("freshness", "pre"),
                Middleware("result", "post"),
                Middleware("audit", "post"),
            ],
        )

        await runtime.execute(
            tool_call_id="call-1",
            name="ordered",
            arguments={},
        )

        self.assertEqual(events, [
            "cancellation",
            "hook",
            "permission",
            "freshness",
            "tool",
            "result",
            "audit",
        ])


if __name__ == "__main__":
    unittest.main()
