from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from lion_code.core.cancellation import CancellationToken
from lion_code.permission_state import (
    PermissionController,
    PermissionMode,
    PermissionState,
)
from lion_code.runtime.session_identity import SessionIdentityState
from lion_code.tooling.context import ToolContext
from lion_code.tooling.middleware import PermissionMiddleware
from lion_code.tooling.permission import PermissionPolicy, reset_permission_cache
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.runtime import ToolRuntime
from lion_code.tooling.types import LionTool, ToolCapabilities, ToolResult


def _tool(name: str, capabilities: ToolCapabilities, executed: list[str]) -> LionTool:
    async def execute(_context, _tool_call_id, _arguments, _on_update):
        executed.append(name)
        return ToolResult(content="executed")

    return LionTool(
        name=name,
        label=name,
        description=name,
        parameters={"type": "object", "properties": {}},
        execute_fn=execute,
        capabilities=capabilities,
    )


def _runtime(
    tool,
    *,
    mode: PermissionMode,
    policy,
    confirm_fn=None,
):
    registry = ToolRegistry()
    registry.register(tool)
    permission = PermissionController(PermissionState(mode))
    context = ToolContext(
        session=SessionIdentityState("session", "2026-08-09T00:00:00Z"),
        cancellation=CancellationToken(),
        cwd=policy.cwd,
        registry=registry,
        permission=permission,
        read_file_state={},
        confirm_fn=confirm_fn,
    )
    return (
        ToolRuntime(
            registry,
            context,
            [PermissionMiddleware(policy, permission)],
        ),
        context,
        permission,
    )


class TestPermissionMiddleware(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        reset_permission_cache()

    async def test_explicit_deny_beats_bypass(self):
        executed = []
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as cwd_dir:
            settings = Path(cwd_dir) / ".claude" / "settings.json"
            settings.parent.mkdir()
            settings.write_text(
                json.dumps({"permissions": {"deny": ["run_shell"]}}),
                encoding="utf-8",
            )
            policy = PermissionPolicy(home=Path(home_dir), cwd=Path(cwd_dir))
            runtime, _, _ = _runtime(
                _tool("run_shell", ToolCapabilities(executes_process=True), executed),
                mode="bypassPermissions",
                policy=policy,
            )

            result = await runtime.execute(
                tool_call_id="call-1",
                name="run_shell",
                arguments={"command": "echo ok"},
            )

        self.assertTrue(result.is_error)
        self.assertEqual(executed, [])

    async def test_confirmation_runs_once_for_cached_reason(self):
        executed = []
        confirm = AsyncMock(return_value=True)
        policy = PermissionPolicy()
        runtime, _, permission = _runtime(
            _tool(
                "external",
                ToolCapabilities(requires_confirmation=True),
                executed,
            ),
            mode="default",
            policy=policy,
            confirm_fn=confirm,
        )

        for call_id in ("call-1", "call-2"):
            result = await runtime.execute(
                tool_call_id=call_id,
                name="external",
                arguments={},
            )
            self.assertFalse(result.is_error)

        confirm.assert_awaited_once()
        self.assertTrue(permission.is_confirmed("use tool: external"))
        self.assertEqual(executed, ["external", "external"])

    async def test_dangerous_shell_reconfirmation_is_cached(self):
        executed = []
        confirm = AsyncMock(return_value=True)
        policy = PermissionPolicy()
        runtime, _, permission = _runtime(
            _tool("run_shell", ToolCapabilities(executes_process=True), executed),
            mode="default",
            policy=policy,
            confirm_fn=confirm,
        )

        for call_id in ("call-1", "call-2"):
            result = await runtime.execute(
                tool_call_id=call_id,
                name="run_shell",
                arguments={"command": "rm -rf /tmp/x"},
            )
            self.assertFalse(result.is_error)

        # 同一会话内重复的相同确认原因只询问一次（Controller 缓存）。
        confirm.assert_awaited_once()
        self.assertTrue(permission.is_confirmed("rm -rf /tmp/x"))
        self.assertEqual(executed, ["run_shell", "run_shell"])

    async def test_user_denial_blocks_tool(self):
        executed = []
        confirm = AsyncMock(return_value=False)
        policy = PermissionPolicy()
        runtime, _, _ = _runtime(
            _tool("run_shell", ToolCapabilities(executes_process=True), executed),
            mode="default",
            policy=policy,
            confirm_fn=confirm,
        )

        result = await runtime.execute(
            tool_call_id="call-1",
            name="run_shell",
            arguments={"command": "rm -rf /tmp/x"},
        )

        self.assertTrue(result.is_error)
        self.assertEqual(executed, [])

    async def test_existing_context_observes_live_mode_change(self):
        executed = []
        confirm = AsyncMock(return_value=False)
        runtime, context, permission = _runtime(
            _tool(
                "external",
                ToolCapabilities(requires_confirmation=True),
                executed,
            ),
            mode="default",
            policy=PermissionPolicy(),
            confirm_fn=confirm,
        )

        permission.set_mode("bypassPermissions")
        result = await runtime.execute(
            tool_call_id="call-1",
            name="external",
            arguments={},
        )

        self.assertIs(context.permission, permission)
        self.assertEqual(context.permission.mode, "bypassPermissions")
        self.assertFalse(result.is_error)
        confirm.assert_not_awaited()
        self.assertEqual(executed, ["external"])


if __name__ == "__main__":
    unittest.main()
