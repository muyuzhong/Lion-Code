from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lion_code.core.cancellation import CancellationToken
from lion_code.permission_state import PermissionController, PermissionState
from lion_code.session_identity import SessionIdentityState
from lion_code.tooling.builtin import BUILTIN_TOOL_NAMES, create_builtin_tools
from lion_code.tooling.context import ToolContext
from lion_code.tooling.execution import LocalCommandExecutionBackend
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.runtime import ToolRuntime


class _FakeCommandBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float]] = []

    def run(self, command: str, *, timeout_ms: float = 30000.0) -> str:
        self.calls.append((command, timeout_ms))
        return f"ran: {command}"


class TestBuiltinTools(unittest.IsolatedAsyncioTestCase):
    def test_builtin_schema_has_single_object_source(self):
        tools = create_builtin_tools(_FakeCommandBackend())

        self.assertEqual({tool.name for tool in tools}, BUILTIN_TOOL_NAMES)
        schemas = {tool.name: tool.to_anthropic_schema() for tool in tools}
        self.assertEqual(schemas["read_file"]["name"], "read_file")
        self.assertEqual(
            schemas["read_file"]["input_schema"],
            tools[0].parameters,
        )

    async def test_read_file_runs_through_runtime(self):
        registry = ToolRegistry()
        for tool in create_builtin_tools(_FakeCommandBackend()):
            registry.register(tool)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hello.txt"
            path.write_text("第一行\nsecond", encoding="utf-8")

            context = ToolContext(
                session=SessionIdentityState("session", "2026-08-09T00:00:00Z"),
                cancellation=CancellationToken(),
                cwd=Path(directory),
                registry=registry,
                permission=PermissionController(PermissionState("default")),
                read_file_state={},
            )
            result = await ToolRuntime(registry, context).execute(
                tool_call_id="call-1",
                name="read_file",
                arguments={"file_path": str(path)},
            )

        self.assertFalse(result.is_error)
        self.assertIn("1 | 第一行", result.content)
        self.assertIn("2 | second", result.content)

    def test_capabilities_drive_execution_mode(self):
        tools = {tool.name: tool for tool in create_builtin_tools(_FakeCommandBackend())}

        self.assertEqual(tools["read_file"].execution_mode, "parallel")
        self.assertTrue(tools["read_file"].capabilities.read_only)
        self.assertEqual(tools["write_file"].execution_mode, "sequential")
        self.assertTrue(
            tools["write_file"].capabilities.requires_read_before_write
        )

    async def test_run_shell_binds_profile_selected_backend(self):
        backend = _FakeCommandBackend()
        registry = ToolRegistry()
        for tool in create_builtin_tools(backend):
            registry.register(tool)

        context = ToolContext(
            session=SessionIdentityState("session", "2026-08-09T00:00:00Z"),
            cancellation=CancellationToken(),
            cwd=Path.cwd(),
            registry=registry,
            permission=PermissionController(PermissionState("bypassPermissions")),
            read_file_state={},
        )
        result = await ToolRuntime(registry, context).execute(
            tool_call_id="call-1",
            name="run_shell",
            arguments={"command": "echo hi", "timeout": 1500},
        )

        self.assertEqual(backend.calls, [("echo hi", 1500.0)])
        self.assertEqual(result.content, "ran: echo hi")

    def test_local_backend_keeps_shell_output_contract(self):
        backend = LocalCommandExecutionBackend()

        self.assertEqual(backend.run("echo hi"), "hi\n")
        self.assertIn("Command failed (exit code 1)", backend.run("exit 1"))
        self.assertIn("timed out", backend.run("ping -n 5 127.0.0.1", timeout_ms=100))


if __name__ == "__main__":
    unittest.main()
