from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from lion_code.core.cancellation import CancellationToken
from lion_code.permission_state import PermissionController, PermissionState
from lion_code.runtime.session_identity import SessionIdentityState
from lion_code.tooling.audit import ExecutionAuditLog
from lion_code.tooling.context import ToolContext
from lion_code.tooling.middleware import AuditMiddleware
from lion_code.tooling.output_sanitizer import OutputSanitizerMiddleware
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.runtime import ToolRuntime
from lion_code.tooling.secret_provider import (
    SecretStore,
    load_or_create_key,
    load_secret_store,
)
from lion_code.tooling.types import LionTool, ToolCapabilities, ToolResult

SECRET = "sk-live-abcdef123456"


def _store(values: dict[str, str]) -> SecretStore:
    return SecretStore(values, b"unit-test-key")


def _tool(name: str, content: str) -> LionTool:
    async def execute(_context, _tool_call_id, _arguments, _on_update):
        return ToolResult(content=content)

    return LionTool(
        name=name,
        description=name,
        parameters={"type": "object", "properties": {}},
        execute_fn=execute,
        capabilities=ToolCapabilities(),
    )


def _runtime(tool: LionTool, store: SecretStore, audit_log=None) -> ToolRuntime:
    registry = ToolRegistry()
    registry.register(tool)
    middleware = [OutputSanitizerMiddleware(store)]
    if audit_log is not None:
        middleware.append(AuditMiddleware())
    context = ToolContext(
        session=SessionIdentityState("session", "2026-08-22T00:00:00Z"),
        cancellation=CancellationToken(),
        cwd=Path.cwd(),
        registry=registry,
        permission=PermissionController(PermissionState("default")),
        read_file_state={},
        audit_log=audit_log,
    )
    return ToolRuntime(registry, context, middleware)


def _run(tool: LionTool, store: SecretStore, audit_log=None) -> ToolResult:
    runtime = _runtime(tool, store, audit_log)
    return asyncio.run(
        runtime.execute(tool_call_id="call-1", name=tool.name, arguments={})
    )


class TestSecretStore(unittest.TestCase):
    def test_short_values_are_not_registered(self) -> None:
        store = _store({"SHORT": "abc"})
        self.assertFalse(store.fingerprints())
        self.assertFalse(store.matches("abc"))

    def test_raw_and_base64_variants_match(self) -> None:
        import base64

        store = _store({"API_KEY": SECRET})
        self.assertTrue(store.matches(SECRET))
        self.assertTrue(store.matches(base64.b64encode(SECRET.encode()).decode()))

    def test_non_secret_text_does_not_match(self) -> None:
        store = _store({"API_KEY": SECRET})
        self.assertFalse(store.matches("ordinary-token"))

    def test_env_name_pattern_registration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / ".env").write_text(
                "DB_TOKEN=token-from-env-file\n", encoding="utf-8"
            )
            environ = {
                "PROVIDER_API_KEY": SECRET,
                "HOME": "/home/user",
                "PATH": "/usr/bin",
                "RELEASE_PASSWORD": "hunter2hunter2",
            }
            store = load_secret_store(
                workspace=workspace,
                key_file=workspace / "key",
                environ=environ,
            )
        self.assertTrue(store.matches(SECRET))
        self.assertTrue(store.matches("token-from-env-file"))
        self.assertTrue(store.matches("hunter2hunter2"))
        self.assertFalse(store.matches("/usr/bin"))
        self.assertFalse(store.matches("/home/user"))

    def test_key_file_created_once_and_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_file = Path(directory) / "sub" / "sanitizer.key"
            first = load_or_create_key(key_file)
            self.assertTrue(key_file.exists())
            self.assertEqual(load_or_create_key(key_file), first)


class TestOutputSanitizer(unittest.TestCase):
    def test_bare_value_line_is_redacted(self) -> None:
        store = _store({"API_KEY": SECRET})
        result = _run(_tool("run_shell", f"noise\n{SECRET}\n"), store)
        self.assertEqual(result.content, "noise\n***\n")
        self.assertEqual(result.details["sanitizer_hits"], 1)

    def test_key_value_pair_is_redacted(self) -> None:
        store = _store({"API_KEY": SECRET})
        result = _run(_tool("read_file", f"API_KEY={SECRET}\n"), store)
        self.assertEqual(result.content, "API_KEY=***\n")

    def test_quoted_multiword_value_is_redacted(self) -> None:
        secret = "my secret value 42"
        store = _store({"DB_PASSWORD": secret})
        result = _run(_tool("read_file", f'DB_PASSWORD="{secret}"\n'), store)
        self.assertEqual(result.content, 'DB_PASSWORD="***"\n')

    def test_token_with_punctuation_is_redacted(self) -> None:
        store = _store({"API_KEY": SECRET})
        result = _run(_tool("grep_search", f"auth failed for {SECRET}, retry\n"), store)
        self.assertEqual(result.content, "auth failed for ***, retry\n")

    def test_clean_output_passes_through_unchanged(self) -> None:
        store = _store({"API_KEY": SECRET})
        content = "all good\nnothing secret here\n"
        result = _run(_tool("list_files", content), store)
        self.assertEqual(result.content, content)
        self.assertNotIn("sanitizer_hits", result.details)

    def test_multiple_hits_are_counted(self) -> None:
        store = _store({"API_KEY": SECRET})
        result = _run(_tool("run_shell", f"{SECRET} then {SECRET} again\n"), store)
        self.assertEqual(result.content, "*** then *** again\n")
        self.assertEqual(result.details["sanitizer_hits"], 2)

    def test_empty_store_is_a_no_op(self) -> None:
        result = _run(_tool("run_shell", f"{SECRET}\n"), _store({}))
        self.assertEqual(result.content, f"{SECRET}\n")
        self.assertNotIn("sanitizer_hits", result.details)

    def test_sanitizer_runs_before_audit_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit_log = ExecutionAuditLog(Path(directory) / "execution.audit")
            store = _store({"API_KEY": SECRET})
            result = _run(_tool("run_shell", f"echo {SECRET}\n"), store, audit_log)
            row = (Path(directory) / "execution.audit").read_text(encoding="utf-8")
        self.assertEqual(result.details["sanitizer_hits"], 1)
        self.assertNotIn(SECRET, row)
        self.assertIn('"sanitizer_hits":1', row)


class TestSanitizedPathsByToolShape(unittest.TestCase):
    """四种工具输出形态（shell/read/grep/web）全部经同一窄腰 redact。"""

    def test_run_shell_output_shape(self) -> None:
        store = _store({"API_KEY": SECRET})
        result = _run(_tool("run_shell", f"deploy ok\ntoken={SECRET}\n"), store)
        self.assertNotIn(SECRET, result.content)

    def test_read_file_output_shape(self) -> None:
        store = _store({"API_KEY": SECRET})
        result = _run(_tool("read_file", f"1\texport KEY={SECRET}\n2\tdone\n"), store)
        self.assertNotIn(SECRET, result.content)

    def test_grep_search_output_shape(self) -> None:
        store = _store({"API_KEY": SECRET})
        result = _run(_tool("grep_search", f"config.py:12: KEY = '{SECRET}'\n"), store)
        self.assertNotIn(SECRET, result.content)

    def test_web_fetch_output_shape(self) -> None:
        store = _store({"API_KEY": SECRET})
        result = _run(_tool("web_fetch", f"<html>api_key: {SECRET}</html>\n"), store)
        self.assertNotIn(SECRET, result.content)


class TestEdgeCaseRedaction(unittest.TestCase):
    def test_env_inline_comment_is_stripped_at_registration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / ".env").write_text(
                "API_KEY=value12345 # note\n", encoding="utf-8"
            )
            store = load_secret_store(
                workspace=workspace,
                key_file=workspace / "key",
                environ={},
            )
        self.assertTrue(store.matches("value12345"))
        self.assertFalse(store.matches("value12345 # note"))

    def test_env_quoted_value_keeps_hash_inside(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / ".env").write_text('API_KEY="value#12345"\n', encoding="utf-8")
            store = load_secret_store(
                workspace=workspace,
                key_file=workspace / "key",
                environ={},
            )
        self.assertTrue(store.matches("value#12345"))

    def test_crlf_output_is_redacted(self) -> None:
        store = _store({"API_KEY": SECRET})
        result = _run(_tool("run_shell", f"line\r\n{SECRET}\r\n"), store)
        self.assertNotIn(SECRET, result.content)
        self.assertIn("***", result.content)

    def test_base64_form_through_full_chain(self) -> None:
        import base64

        encoded = base64.b64encode(SECRET.encode()).decode()
        store = _store({"API_KEY": SECRET})
        result = _run(_tool("run_shell", f"bearer {encoded}\n"), store)
        self.assertNotIn(encoded, result.content)

    def test_tool_exception_message_is_sanitized(self) -> None:
        store = _store({"API_KEY": SECRET})

        def _raising() -> LionTool:
            async def execute(_context, _tool_call_id, _arguments, _on_update):
                raise ValueError(f"invalid config value: {SECRET}")

            return LionTool(
                name="custom",
                description="custom",
                parameters={"type": "object", "properties": {}},
                execute_fn=execute,
                capabilities=ToolCapabilities(),
            )

        result = _run(_raising(), store)
        self.assertTrue(result.is_error)
        self.assertIn("ValueError", result.content)
        self.assertNotIn(SECRET, result.content)


if __name__ == "__main__":
    unittest.main()
