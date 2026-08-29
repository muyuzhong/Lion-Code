from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from lion_code.core.cancellation import CancellationToken
from lion_code.permission_state import PermissionController, PermissionState
from lion_code.runtime.session_identity import SessionIdentityState
from lion_code.tooling.audit import ExecutionAuditLog
from lion_code.tooling.context import ToolContext
from lion_code.tooling.middleware import WorkspaceSnapshotMiddleware
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.runtime import ToolRuntime
from lion_code.tooling.snapshot import WorkspaceSnapshot
from lion_code.tooling.types import LionTool, ToolCapabilities, ToolResult


def _context(
    root: Path,
    registry: ToolRegistry,
    *,
    audit: ExecutionAuditLog | None = None,
) -> ToolContext:
    return ToolContext(
        session=SessionIdentityState("session", "2026-08-21T00:00:00Z"),
        cancellation=CancellationToken(),
        cwd=root,
        registry=registry,
        permission=PermissionController(PermissionState("bypassPermissions")),
        read_file_state={},
        audit_log=audit,
    )


def _tool(
    name: str,
    capabilities: ToolCapabilities,
    execute_fn,
) -> LionTool:
    return LionTool(
        name=name,
        description=name,
        parameters={"type": "object", "properties": {}},
        execute_fn=execute_fn,
        capabilities=capabilities,
    )


class TestSnapshotRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_write_and_shell_tools_get_pre_execution_snapshot_ids(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            tempfile.TemporaryDirectory() as storage_directory,
        ):
            root = Path(directory)
            store = Path(storage_directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            snapshot = WorkspaceSnapshot(root, store)
            registry = ToolRegistry()

            async def write(context, _call_id, _arguments, _on_update):
                (context.cwd / "written.txt").write_text("written", encoding="utf-8")
                return ToolResult(content="written")

            async def shell(_context, _call_id, arguments, _on_update):
                return ToolResult(content=str(arguments["command"]))

            registry.register(
                _tool("write_file", ToolCapabilities(mutates_workspace=True), write)
            )
            registry.register(
                _tool("run_shell", ToolCapabilities(executes_process=True), shell)
            )
            context = _context(root, registry)
            runtime = ToolRuntime(
                registry,
                context,
                [WorkspaceSnapshotMiddleware(snapshot)],
            )

            write_result = await runtime.execute(
                tool_call_id="write-1",
                name="write_file",
                arguments={},
            )
            shell_results = [
                await runtime.execute(
                    tool_call_id=f"shell-{index}",
                    name="run_shell",
                    arguments={"command": f"echo {index}"},
                )
                for index in range(2)
            ]

            write_snapshot_id = write_result.details.get("snapshot_id")
            shell_snapshot_ids = [
                result.details.get("snapshot_id") for result in shell_results
            ]
            self.assertIsInstance(write_snapshot_id, str)
            self.assertTrue(all(isinstance(item, str) for item in shell_snapshot_ids))
            self.assertEqual(len(set(shell_snapshot_ids)), 2)
            self.assertEqual(len(list(store.iterdir())), 3)

    async def test_snapshot_and_audit_can_both_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = ToolRegistry()

            async def execute(context, _call_id, _arguments, _on_update):
                (context.cwd / "normal.txt").write_text("ok", encoding="utf-8")
                return ToolResult(content="ok")

            registry.register(
                _tool("write_file", ToolCapabilities(mutates_workspace=True), execute)
            )
            context = _context(root, registry)
            runtime = ToolRuntime(registry, context)

            result = await runtime.execute(
                tool_call_id="write-1",
                name="write_file",
                arguments={},
            )

            self.assertFalse(result.is_error)
            self.assertEqual(result.details, {})
            self.assertEqual((root / "normal.txt").read_text(encoding="utf-8"), "ok")
            self.assertFalse((root / ".lion-code").exists())


if __name__ == "__main__":
    unittest.main()
