from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from lion_code.core.cancellation import CancellationToken
from lion_code.permission_state import PermissionController, PermissionState
from lion_code.runtime.session_identity import SessionIdentityState
from lion_code.tooling.audit import ExecutionAuditLog
from lion_code.tooling.context import ToolContext
from lion_code.tooling.middleware import AuditMiddleware, PermissionMiddleware
from lion_code.tooling.permission import (
    PermissionPolicy,
    is_publish_like,
    reset_permission_cache,
)
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.runtime import ToolRuntime
from lion_code.tooling.types import LionTool, ToolCapabilities, ToolResult


def _shell_tool() -> LionTool:
    async def execute(_context, _tool_call_id, _arguments, _on_update):
        return ToolResult(content="executed")

    return LionTool(
        name="run_shell",
        label="run_shell",
        description="run_shell",
        parameters={"type": "object", "properties": {}},
        execute_fn=execute,
        capabilities=ToolCapabilities(executes_process=True),
    )


def _runtime(mode: str, audit_log=None, *, home: Path, cwd: Path) -> ToolRuntime:
    tool = _shell_tool()
    registry = ToolRegistry()
    registry.register(tool)
    permission = PermissionController(PermissionState(mode))
    policy = PermissionPolicy(home=home, cwd=cwd)
    middleware = [PermissionMiddleware(policy, permission)]
    if audit_log is not None:
        middleware.append(AuditMiddleware())
    context = ToolContext(
        session=SessionIdentityState("session", "2026-08-22T00:00:00Z"),
        cancellation=CancellationToken(),
        cwd=cwd,
        registry=registry,
        permission=permission,
        read_file_state={},
        audit_log=audit_log,
    )
    return ToolRuntime(registry, context, middleware)


def _run(runtime: ToolRuntime, command: str) -> ToolResult:
    return asyncio.run(
        runtime.execute(
            tool_call_id="call-1",
            name="run_shell",
            arguments={"command": command},
        )
    )


class TestPublishContexts(unittest.TestCase):
    def tearDown(self):
        reset_permission_cache()

    def test_publish_prefixes_match(self) -> None:
        self.assertTrue(is_publish_like("npm publish"))
        self.assertTrue(is_publish_like("npm publish --access public"))
        self.assertTrue(is_publish_like("  docker push repo:tag"))
        self.assertTrue(is_publish_like("twine upload dist/*"))
        self.assertFalse(is_publish_like("npm install"))
        self.assertFalse(is_publish_like("git pull"))
        self.assertFalse(is_publish_like("npmx publishx"))

    def test_publish_command_requires_confirmation(self) -> None:
        with (
            tempfile.TemporaryDirectory() as home,
            tempfile.TemporaryDirectory() as cwd,
        ):
            policy = PermissionPolicy(home=Path(home), cwd=Path(cwd))
            decision = policy.check(
                tool=_shell_tool(),
                arguments={"command": "npm publish"},
                mode="default",
            )
        self.assertEqual(decision.action, "confirm")
        self.assertEqual(decision.message, "npm publish")


class TestGracefulShutdown(unittest.TestCase):
    def tearDown(self):
        reset_permission_cache()

    def _tmp(self):
        home = tempfile.TemporaryDirectory()
        cwd = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.addCleanup(cwd.cleanup)
        return Path(home.name), Path(cwd.name)

    def test_dontAsk_decision_is_budget_exceeded(self) -> None:
        home, cwd = self._tmp()
        policy = PermissionPolicy(home=home, cwd=cwd)
        decision = policy.check(
            tool=_shell_tool(),
            arguments={"command": "rm -rf build"},
            mode="dontAsk",
        )
        self.assertEqual(decision.action, "deny")
        self.assertTrue(decision.budget_exceeded)
        self.assertEqual(decision.message, "rm -rf build")

    def test_shutdown_result_is_structured_and_terminates(self) -> None:
        home, cwd = self._tmp()
        result = _run(_runtime("dontAsk", home=home, cwd=cwd), "npm publish")
        self.assertTrue(result.is_error)
        self.assertTrue(result.terminate)
        self.assertTrue(result.details["budget_exceeded"])
        self.assertEqual(result.details["trigger"], "npm publish")
        self.assertIn("NOT executed", result.content)
        self.assertIn("suspended", result.content)

    def test_shutdown_audit_row_is_blocked_with_note(self) -> None:
        home, cwd = self._tmp()
        with tempfile.TemporaryDirectory() as directory:
            audit_log = ExecutionAuditLog(Path(directory) / "execution.audit")
            result = _run(
                _runtime("dontAsk", audit_log, home=home, cwd=cwd), "npm publish"
            )
            row = json.loads(
                (Path(directory) / "execution.audit").read_text(encoding="utf-8")
            )
        self.assertTrue(result.terminate)
        self.assertEqual(row["result"], "blocked")
        self.assertIn("budget_exceeded", row["notes"][0])
        self.assertEqual(row["tool"], "run_shell")

    def test_normal_deny_is_not_budget_exceeded(self) -> None:
        with (
            tempfile.TemporaryDirectory() as home,
            tempfile.TemporaryDirectory() as cwd,
        ):
            settings = Path(cwd) / ".claude" / "settings.json"
            settings.parent.mkdir()
            settings.write_text(
                json.dumps({"permissions": {"deny": ["run_shell"]}}),
                encoding="utf-8",
            )
            policy = PermissionPolicy(home=Path(home), cwd=Path(cwd))
            decision = policy.check_hard_boundaries(
                tool=_shell_tool(),
                arguments={"command": "ls"},
                mode="default",
            )
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.action, "deny")
        self.assertFalse(decision.budget_exceeded)


if __name__ == "__main__":
    unittest.main()
