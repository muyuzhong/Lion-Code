"""Tool adapter behavior contracts: schema, results, errors, concurrency, activation."""

from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from lion_code.adapters import adapt_active_tools, adapt_lion_tool, to_core_result
from lion_code.core import CancellationToken
from lion_code.permission_state import PermissionController, PermissionState
from lion_code.session_identity import SessionIdentityState
from lion_code.tooling.context import ToolContext
from lion_code.tooling.middleware import CancellationMiddleware
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.runtime import ToolRuntime
from lion_code.tooling.types import LionTool, ToolCapabilities, ToolResult


class _Controller:
    pass


def _context(registry: ToolRegistry) -> ToolContext:
    return ToolContext(
        session=SessionIdentityState("session", "2026-08-09T00:00:00Z"),
        cancellation=CancellationToken(),
        cwd=Path.cwd(),
        registry=registry,
        permission=PermissionController(PermissionState("default")),
        read_file_state={},
    )


def _tool(
    name: str = "echo",
    execute_fn=None,
    *,
    mode: str = "sequential",
    **capabilities,
) -> LionTool:
    async def _noop(_ctx, _id, _args, _on_update):
        return ToolResult(content="ok")

    return LionTool(
        name=name,
        label=name,
        description=name,
        parameters={"type": "object", "properties": {}},
        execute_fn=execute_fn or _noop,
        capabilities=ToolCapabilities(**capabilities),
        execution_mode=mode,
    )


def _runtime(tools, middleware=()) -> ToolRuntime:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return ToolRuntime(registry, _context(registry), middleware)


class TestToolMetadataMapping(unittest.TestCase):
    def test_maps_tool_metadata(self):
        lion_tool = _tool("echo")
        runtime = _runtime([lion_tool])
        core_tool = adapt_lion_tool(lion_tool, runtime)

        self.assertEqual(core_tool.name, "echo")
        self.assertEqual(core_tool.description, "echo")
        self.assertEqual(core_tool.parameters, lion_tool.parameters)


class TestResultMapping(unittest.IsolatedAsyncioTestCase):
    async def test_maps_success_result(self):
        async def execute(_ctx, _id, _args, _on_update):
            return ToolResult(
                content="hello",
                details={"k": "v"},
                terminate=True,
            )

        lion_tool = _tool("echo", execute)
        runtime = _runtime([lion_tool])
        core_tool = adapt_lion_tool(lion_tool, runtime)

        result = await core_tool.execute("call-1", {"value": "hello"})

        self.assertEqual(result.text, "hello")
        self.assertFalse(result.is_error)
        self.assertEqual(result.details, {"k": "v"})
        self.assertTrue(result.terminate)

    async def test_to_core_result_preserves_error_state(self):
        # A Lion runtime denial surfaces as ToolResult(is_error=True), not an
        # exception. The conversion must carry that flag so the core loop does
        # not reclassify the denial as a successful tool call.
        result = to_core_result(
            ToolResult(content="Action denied: blocked", is_error=True)
        )

        self.assertTrue(result.is_error)
        self.assertEqual(result.text, "Action denied: blocked")


class TestRuntimeErrorPreservation(unittest.IsolatedAsyncioTestCase):
    async def test_middleware_denial_flows_as_structured_error(self):
        async def execute(_ctx, _id, _args, _on_update):
            return ToolResult(content="should not reach the tool")

        class DenyMiddleware:
            phase = "pre"

            async def handle(self, *, tool, context, tool_call_id, arguments, call_next, **_):
                return ToolResult(
                    content="Action denied: blocked by policy",
                    is_error=True,
                )

        lion_tool = _tool("guarded", execute)
        runtime = _runtime([lion_tool], [DenyMiddleware()])
        core_tool = adapt_lion_tool(lion_tool, runtime)

        result = await core_tool.execute("call-1", {"path": "blocked"})

        self.assertTrue(result.is_error)
        self.assertIn("denied", result.text.lower())


class TestMiddlewareExecution(unittest.IsolatedAsyncioTestCase):
    async def test_middleware_runs_once_per_call(self):
        # The adapter must route through ToolRuntime.execute (which drives the
        # middleware chain), not call LionTool.execute directly. A direct call
        # would bypass permission/hook/freshness policy and leave calls at 0.
        calls = 0

        class CountingMiddleware:
            phase = "pre"

            async def handle(self, *, call_next, **_):
                nonlocal calls
                calls += 1
                return await call_next()

        lion_tool = _tool("echo")
        runtime = _runtime([lion_tool], [CountingMiddleware()])
        core_tool = adapt_lion_tool(lion_tool, runtime)

        await core_tool.execute("call-1", {})

        self.assertEqual(calls, 1)

    async def test_core_signal_reaches_runtime_cancellation_middleware(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        executed = False

        class DelayMiddleware:
            phase = "pre"

            async def handle(self, *, call_next, **_):
                entered.set()
                await release.wait()
                return await call_next()

        async def execute(_ctx, _id, _args, _on_update):
            nonlocal executed
            executed = True
            return ToolResult(content="should not run")

        lion_tool = _tool("slow", execute)
        runtime = _runtime(
            [lion_tool],
            [DelayMiddleware(), CancellationMiddleware()],
        )
        core_tool = adapt_lion_tool(lion_tool, runtime)
        signal = CancellationToken()

        task = asyncio.create_task(core_tool.execute("call-1", {}, signal))
        await entered.wait()
        signal.cancel()
        release.set()
        result = await asyncio.wait_for(task, timeout=1)

        self.assertTrue(result.is_error)
        self.assertIn("cancelled", result.text.lower())
        self.assertFalse(executed)


class TestConcurrencyMapping(unittest.TestCase):
    def test_execution_mode_follows_lion_capability(self):
        safe = _tool("safe", mode="parallel", read_only=True, concurrency_safe=True)
        mutating = _tool("mutating", mode="parallel", mutates_workspace=True)
        sequential = _tool("seq", mode="sequential", read_only=True, concurrency_safe=True)
        runtime = _runtime([safe, mutating, sequential])

        self.assertEqual(adapt_lion_tool(safe, runtime).execution_mode, "parallel")
        self.assertEqual(adapt_lion_tool(mutating, runtime).execution_mode, "sequential")
        self.assertEqual(adapt_lion_tool(sequential, runtime).execution_mode, "sequential")


class TestDynamicActivation(unittest.TestCase):
    def test_adapt_active_tools_reflects_registry_activation(self):
        # tool_search-style flow: a deferred tool is registered but inactive;
        # after the registry activates it, the next adapt_active_tools() call
        # exposes it to the core loop without any adapter-side caching.
        search = _tool("tool_search", mode="parallel", read_only=True, concurrency_safe=True)
        secret = _tool("secret", deferred=True)
        registry = ToolRegistry()
        registry.register(search)  # not deferred -> active by default
        registry.register(secret)  # deferred -> inactive by default
        runtime = ToolRuntime(registry, _context(registry))

        before = [tool.name for tool in adapt_active_tools(runtime)]
        self.assertEqual(before, ["tool_search"])

        registry.activate("secret")

        after = [tool.name for tool in adapt_active_tools(runtime)]
        self.assertEqual(after, ["tool_search", "secret"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
