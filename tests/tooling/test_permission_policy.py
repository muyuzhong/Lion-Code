from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lion_code.tooling.permission import PermissionPolicy, reset_permission_cache
from lion_code.tooling.types import LionTool, ToolCapabilities, ToolResult


async def _execute(_context, _tool_call_id, _arguments, _on_update):
    return ToolResult(content="ok")


def _tool(name: str, **capabilities) -> LionTool:
    return LionTool(
        name=name,
        description=name,
        parameters={"type": "object", "properties": {}},
        execute_fn=_execute,
        capabilities=ToolCapabilities(**capabilities),
    )


class TestPermissionPolicy(unittest.TestCase):
    def tearDown(self):
        reset_permission_cache()

    def test_explicit_deny_beats_bypass(self):
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as cwd_dir:
            settings = Path(cwd_dir) / ".claude" / "settings.json"
            settings.parent.mkdir()
            settings.write_text(
                json.dumps({"permissions": {"deny": ["run_shell"]}}),
                encoding="utf-8",
            )
            decision = PermissionPolicy(
                home=Path(home_dir),
                cwd=Path(cwd_dir),
            ).check(
                tool=_tool("run_shell", executes_process=True),
                arguments={"command": "echo ok"},
                mode="bypassPermissions",
            )

        self.assertEqual(decision.action, "deny")

    def test_explicit_allow_beats_dangerous_confirm(self):
        with tempfile.TemporaryDirectory() as home_dir, tempfile.TemporaryDirectory() as cwd_dir:
            settings = Path(cwd_dir) / ".claude" / "settings.json"
            settings.parent.mkdir()
            settings.write_text(
                json.dumps(
                    {"permissions": {"allow": ["run_shell(rm -rf cache)"]}}
                ),
                encoding="utf-8",
            )
            decision = PermissionPolicy(
                home=Path(home_dir),
                cwd=Path(cwd_dir),
            ).check(
                tool=_tool("run_shell", executes_process=True),
                arguments={"command": "rm -rf cache"},
                mode="default",
            )

        self.assertEqual(decision.action, "allow")

    def test_read_only_tool_is_allowed(self):
        decision = PermissionPolicy().check(
            tool=_tool("read_file", read_only=True),
            arguments={"file_path": "README.md"},
            mode="default",
        )

        self.assertEqual(decision.action, "allow")

    def test_dangerous_command_requires_confirmation(self):
        decision = PermissionPolicy().check(
            tool=_tool("run_shell", executes_process=True),
            arguments={"command": "rm -rf /tmp/x"},
            mode="default",
        )

        self.assertEqual(decision.action, "confirm")
        self.assertEqual(decision.message, "rm -rf /tmp/x")

    def test_dont_ask_auto_denies_confirmation(self):
        decision = PermissionPolicy().check(
            tool=_tool("run_shell", executes_process=True),
            arguments={"command": "rm -rf /tmp/x"},
            mode="dontAsk",
        )

        self.assertEqual(decision.action, "deny")

    def test_bypass_skips_confirmation(self):
        decision = PermissionPolicy().check(
            tool=_tool("run_shell", executes_process=True),
            arguments={"command": "rm -rf /tmp/x"},
            mode="bypassPermissions",
        )

        self.assertEqual(decision.action, "allow")


if __name__ == "__main__":
    unittest.main()
