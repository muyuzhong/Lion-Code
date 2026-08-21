from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lion_code.tooling.audit import ExecutionAuditLog, ExecutionEvent
from lion_code.tooling.types import LionTool, ToolCapabilities, ToolResult


def _tool(name: str, *, executes_process: bool = False) -> LionTool:
    async def execute(_context, _tool_call_id, _arguments, _on_update):
        return ToolResult(content="ok")

    return LionTool(
        name=name,
        label=name,
        description=name,
        parameters={"type": "object", "properties": {}},
        execute_fn=execute,
        capabilities=ToolCapabilities(executes_process=executes_process),
    )


class TestExecutionAudit(unittest.TestCase):
    def test_append_uses_fixed_execution_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "execution.audit"
            audit = ExecutionAuditLog(path)
            audit.append(
                ExecutionEvent(
                    tool="write_file",
                    command_or_args='{"file_path":"a.txt"}',
                    snapshot_id="snapshot-1",
                    result="success",
                )
            )

            row = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(
                set(row),
                {
                    "event",
                    "tool",
                    "command_or_args",
                    "timestamp",
                    "snapshot_id",
                    "result",
                    "destination",
                    "fingerprint_hit",
                    "authorization_source",
                    "sanitizer_hits",
                    "best_effort",
                    "notes",
                },
            )
            self.assertEqual(row["event"], "execution")
            self.assertEqual(row["result"], "success")
            self.assertIsNone(row["destination"])
            self.assertIsNone(row["fingerprint_hit"])
            self.assertIsNone(row["authorization_source"])
            self.assertEqual(row["notes"], [])

    def test_sensitive_file_arguments_are_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "execution.audit"
            audit = ExecutionAuditLog(path)
            audit.record_tool(
                _tool("write_file"),
                {
                    "file_path": ".env.local",
                    "content": "TOKEN=must-not-be-audit-data",
                },
                ToolResult(
                    content="ok",
                    details={"snapshot_id": "snapshot-1"},
                ),
            )

            serialized = path.read_text(encoding="utf-8")
            row = json.loads(serialized)

            self.assertNotIn("must-not-be-audit-data", serialized)
            self.assertEqual(row["snapshot_id"], "snapshot-1")
            self.assertEqual(row["result"], "success")

    def test_shell_command_is_recorded_as_command_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "execution.audit"
            audit = ExecutionAuditLog(path)
            audit.record_tool(
                _tool("run_shell", executes_process=True),
                {"command": "echo hello"},
                ToolResult(content="hello"),
            )

            row = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(row["command_or_args"], "echo hello")


if __name__ == "__main__":
    unittest.main()
