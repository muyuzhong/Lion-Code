"""Memory Capability 工具面测试：metadata、ToolRuntime 端到端与确认路径。

全部使用临时目录中的数据库与 project root，绝不触碰真实
``~/.lion-code/memory.sqlite3``。
"""

from __future__ import annotations

import unittest
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from lion_code.capabilities.memory.capability import create_memory_capability
from lion_code.capabilities.memory.store import DEFAULT_TOKEN_BUDGET, MemoryStore
from lion_code.core.cancellation import CancellationToken
from lion_code.permission_state import (
    PermissionController,
    PermissionMode,
    PermissionState,
)
from lion_code.runtime.session_identity import SessionIdentityState
from lion_code.tooling.context import ToolContext
from lion_code.tooling.middleware import PermissionMiddleware
from lion_code.tooling.permission import PermissionPolicy
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.runtime import ToolRuntime
from lion_code.tooling.types import JSONValue, ToolResult

SESSION_ID = "session-1"
STARTED_AT = "2026-08-23T00:00:00Z"


def _permission_confirm(approved: bool):
    async def confirm(_message: str) -> bool:
        return approved

    return confirm


class _CapabilityTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db_path = self.root / "memory.sqlite3"
        self.project_root = self.root / "project"
        self.project_root.mkdir()
        (self.project_root / "docs").mkdir()
        (self.project_root / "docs" / "ci.md").write_text("ci", encoding="utf-8")
        self.store = MemoryStore(self.db_path, project_key="proj-a")
        self.spec = create_memory_capability(self.store, project_root=self.project_root)
        self.registry = ToolRegistry()
        for source in self.spec.tool_sources:
            for tool in source.tools():
                self.registry.register(tool)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _context(
        self,
        *,
        mode: PermissionMode = "bypassPermissions",
        confirm_fn: Any = None,
    ) -> ToolContext:
        return ToolContext(
            session=SessionIdentityState(SESSION_ID, STARTED_AT),
            cancellation=CancellationToken(),
            cwd=self.project_root,
            registry=self.registry,
            permission=PermissionController(PermissionState(mode)),
            read_file_state={},
            confirm_fn=confirm_fn,
        )

    def _runtime(
        self,
        *,
        mode: PermissionMode = "bypassPermissions",
        confirm_fn: Any = None,
        with_permission: bool = False,
    ) -> ToolRuntime:
        if not with_permission:
            context = self._context(mode=mode, confirm_fn=confirm_fn)
            return ToolRuntime(self.registry, context)
        permission = PermissionController(PermissionState(mode))
        context = ToolContext(
            session=SessionIdentityState(SESSION_ID, STARTED_AT),
            cancellation=CancellationToken(),
            cwd=self.project_root,
            registry=self.registry,
            permission=permission,
            read_file_state={},
            confirm_fn=confirm_fn,
        )
        policy = PermissionPolicy(cwd=self.root, home=self.root)
        return ToolRuntime(
            self.registry,
            context,
            [PermissionMiddleware(policy, permission)],
        )

    async def _execute(
        self,
        name: str,
        arguments: Mapping[str, JSONValue],
        *,
        mode: PermissionMode = "bypassPermissions",
        confirm_fn: Any = None,
        with_permission: bool = False,
    ) -> ToolResult:
        runtime = self._runtime(
            mode=mode, confirm_fn=confirm_fn, with_permission=with_permission
        )
        return await runtime.execute(
            tool_call_id="call-1", name=name, arguments=arguments
        )

    async def remember(
        self,
        name: str = "remember_definition",
        **arguments: JSONValue,
    ) -> ToolResult:
        return await self._execute(name, arguments)


class TestCapabilityShape(_CapabilityTestCase):
    def test_spec_contributes_five_named_tools(self) -> None:
        self.assertEqual(self.spec.name, "memory")
        tools = {tool.name: tool for tool in self.registry.all_tools()}
        self.assertEqual(
            set(tools),
            {
                "recall_memory",
                "remember_definition",
                "remember_behavior",
                "review_memory",
                "manage_memory",
            },
        )

    def test_read_tools_are_parallel_safe(self) -> None:
        for name in ("recall_memory", "review_memory"):
            tool = self.registry.resolve(name)
            self.assertTrue(tool.capabilities.read_only)
            self.assertTrue(tool.capabilities.concurrency_safe)
            self.assertFalse(tool.capabilities.requires_confirmation)
            self.assertEqual(tool.execution_mode, "parallel")
            self.assertTrue(self.runtime_can_parallel(name))

    def test_mutation_tools_require_confirmation(self) -> None:
        for name in (
            "remember_definition",
            "remember_behavior",
            "manage_memory",
        ):
            tool = self.registry.resolve(name)
            self.assertTrue(tool.capabilities.requires_confirmation)
            self.assertFalse(tool.capabilities.read_only)
            self.assertFalse(self.runtime_can_parallel(name))

    def runtime_can_parallel(self, name: str) -> bool:
        runtime = self._runtime()
        return runtime.can_run_parallel(name)


class TestToolEndToEnd(_CapabilityTestCase):
    async def test_remember_and_recall_roundtrip(self) -> None:
        written = await self.remember(
            scope="project",
            stable_key="ci-guard",
            content="CI must pass before merge",
            evidence=["docs/ci.md"],
            paths=["docs/ci.md"],
        )
        self.assertFalse(written.is_error, written.content)
        self.assertIn("remembered m:1 [proj-a/definition] ci-guard", written.content)
        entry_detail = written.details.get("entry")
        assert isinstance(entry_detail, dict)
        self.assertEqual(entry_detail["scope"], "project")
        self.assertEqual(entry_detail["kind"], "definition")
        entry = self.store.get(1)
        assert entry is not None
        self.assertEqual(entry.source_session_id, SESSION_ID)
        self.assertEqual(entry.paths, ("docs/ci.md",))

        recalled = await self._execute("recall_memory", {"query": "ci merge"})
        self.assertFalse(recalled.is_error, recalled.content)
        self.assertIn("Found 1 memory entries for: ci merge", recalled.content)
        self.assertIn("[m:1 proj-a/definition] ci-guard", recalled.content)
        self.assertIn("Evidence: docs/ci.md", recalled.content)
        self.assertEqual(recalled.details.get("truncated"), False)
        entries = recalled.details.get("entries")
        assert isinstance(entries, list)
        self.assertEqual(entries[0]["stable_key"], "ci-guard")

    async def test_remember_behavior_roundtrip(self) -> None:
        result = await self.remember(
            name="remember_behavior",
            scope="long_term",
            stable_key="pr-flow",
            trigger="when merging a PR",
            instruction="wait for CI green before merge",
            evidence=["AGENTS.md"],
            recall_mode="pinned",
        )
        self.assertFalse(result.is_error, result.content)
        recalled = await self._execute("recall_memory", {"query": "PR merging CI"})
        self.assertIn(
            "When: when merging a PR Do: wait for CI green before merge",
            recalled.content,
        )
        entry = self.store.get(1)
        assert entry is not None
        self.assertEqual(entry.recall_mode, "pinned")
        self.assertEqual(entry.trigger, "when merging a PR")

    async def test_recall_reports_stale_candidates_without_mutating(self) -> None:
        await self.remember(
            stable_key="dead-path",
            content="legacy module location",
            evidence=["src/legacy.py"],
            paths=["src/legacy.py"],
        )
        result = await self._execute("recall_memory", {"query": "legacy module"})
        self.assertIn("Found 0 memory entries", result.content)
        self.assertIn("Stale candidates", result.content)
        self.assertIn("m:1 dead-path (missing: src/legacy.py)", result.content)
        candidates = result.details.get("stale_candidates")
        assert isinstance(candidates, list)
        self.assertEqual(candidates[0]["id"], 1)
        # 未自动改库：条目保持 active
        entry = self.store.get(1)
        assert entry is not None
        self.assertEqual(entry.status, "active")

    async def test_recall_token_budget_truncation(self) -> None:
        await self.remember(stable_key="first", content="docker " * 400, evidence=["e"])
        await self.remember(
            stable_key="second", content="docker " * 400, evidence=["e"]
        )
        result = await self._execute("recall_memory", {"query": "docker"})
        self.assertTrue(result.details.get("truncated"))
        self.assertEqual(result.details.get("token_budget"), DEFAULT_TOKEN_BUDGET)
        entries = result.details.get("entries")
        assert isinstance(entries, list)
        self.assertEqual(len(entries), 1)
        self.assertIn("truncated to fit", result.content)

    async def test_recall_include_inactive(self) -> None:
        await self.remember(stable_key="ci-guard", content="ci fact", evidence=["e"])
        await self._execute(
            "manage_memory",
            {"id": 1, "action": "mark_stale", "reason": "old"},
        )
        active_only = await self._execute("recall_memory", {"query": "ci fact"})
        self.assertIn("Found 0 memory entries", active_only.content)
        included = await self._execute(
            "recall_memory", {"query": "ci fact", "include_inactive": True}
        )
        self.assertIn("[stale]", included.content)

    async def test_review_memory_output(self) -> None:
        await self.remember(
            stable_key="ci-guard",
            content="ci fact",
            evidence=["src/legacy.py"],
            paths=["src/legacy.py"],
        )
        result = await self._execute("review_memory", {"older_than_days": 90})
        self.assertFalse(result.is_error, result.content)
        self.assertIn("Memory review", result.content)
        self.assertIn("stale candidates (paths missing): 1", result.content)
        self.assertIn("stale-candidate m:1 ci-guard", result.content)
        self.assertIn("revision chains: 0", result.content)
        chains = result.details.get("revision_chains")
        assert isinstance(chains, list)
        self.assertEqual(chains, [])

    async def test_review_memory_default_arguments(self) -> None:
        result = await self._execute("review_memory", {})
        self.assertFalse(result.is_error, result.content)
        self.assertIn("Memory review", result.content)

    async def test_manage_memory_actions(self) -> None:
        await self.remember(stable_key="ci-guard", content="ci fact", evidence=["e"])
        await self.remember(stable_key="ci-guard", content="ci fact v2", evidence=["e"])
        archived = await self._execute(
            "manage_memory", {"id": 1, "action": "archive", "reason": "cleanup"}
        )
        self.assertIn("archive m:1 ci-guard -> archived (cleanup)", archived.content)
        stale_new = await self._execute(
            "manage_memory", {"id": 2, "action": "mark_stale", "reason": "check"}
        )
        self.assertIn("mark_stale m:2 ci-guard -> stale (check)", stale_new.content)
        restored = await self._execute("manage_memory", {"id": 1, "action": "restore"})
        self.assertIn("restore m:1 ci-guard -> active", restored.content)
        validated = await self._execute(
            "manage_memory", {"id": 1, "action": "validate"}
        )
        self.assertIn("validate m:1 ci-guard -> active", validated.content)
        purged = await self._execute(
            "manage_memory", {"id": 2, "action": "purge", "reason": "wrong"}
        )
        self.assertIn("purged m:2", purged.content)
        self.assertIn("physically deleted", purged.content)
        self.assertIsNone(self.store.get(2))

    async def test_remember_supersede_reported_in_content(self) -> None:
        await self.remember(stable_key="ci-guard", content="v1", evidence=["e"])
        result = await self.remember(
            stable_key="ci-guard", content="v2", evidence=["e"]
        )
        self.assertIn("superseded revision m:1", result.content)


class TestToolErrorPaths(_CapabilityTestCase):
    async def test_remember_definition_rejects_long_term_paths(self) -> None:
        result = await self.remember(
            scope="long_term",
            stable_key="user-env",
            content="fact",
            evidence=["e"],
            paths=["docs/ci.md"],
        )
        self.assertTrue(result.is_error)
        self.assertIn("memory error:", result.content)
        self.assertIn("long_term", result.content)

    async def test_remember_definition_requires_core_arguments(self) -> None:
        result = await self.remember(scope="project", content="no key")
        self.assertTrue(result.is_error)
        self.assertIn("stable_key", result.content)

    async def test_remember_definition_rejects_bad_enum(self) -> None:
        result = await self.remember(
            scope="team", stable_key="k", content="c", evidence=["e"]
        )
        self.assertTrue(result.is_error)
        self.assertIn("scope", result.content)

    async def test_remember_definition_rejects_bad_evidence_type(self) -> None:
        result = await self.remember(stable_key="k", content="c", evidence="not-a-list")
        self.assertTrue(result.is_error)
        self.assertIn("evidence", result.content)
        result = await self.remember(stable_key="k", content="c", evidence=["ok", 5])
        self.assertTrue(result.is_error)
        self.assertIn("evidence", result.content)

    async def test_remember_behavior_requires_trigger(self) -> None:
        result = await self.remember(
            name="remember_behavior",
            scope="project",
            stable_key="k",
            instruction="do it",
            evidence=["e"],
        )
        self.assertTrue(result.is_error)
        self.assertIn("trigger", result.content)

    async def test_recall_rejects_bad_types(self) -> None:
        result = await self._execute("recall_memory", {"query": 42})
        self.assertTrue(result.is_error)
        result = await self._execute(
            "recall_memory", {"query": "ok", "include_inactive": "yes"}
        )
        self.assertTrue(result.is_error)
        result = await self._execute("recall_memory", {"query": "ok", "paths": "x"})
        self.assertTrue(result.is_error)

    async def test_manage_rejects_missing_reason_and_unknown_action(self) -> None:
        await self.remember(stable_key="k", content="c", evidence=["e"])
        result = await self._execute("manage_memory", {"id": 1, "action": "purge"})
        self.assertTrue(result.is_error)
        self.assertIn("requires a reason", result.content)
        result = await self._execute(
            "manage_memory", {"id": 1, "action": "delete", "reason": "x"}
        )
        self.assertTrue(result.is_error)
        self.assertIn("action", result.content)

    async def test_manage_rejects_bad_id(self) -> None:
        result = await self._execute("manage_memory", {"id": 0, "action": "validate"})
        self.assertTrue(result.is_error)
        result = await self._execute("manage_memory", {"id": "1", "action": "validate"})
        self.assertTrue(result.is_error)

    async def test_manage_unknown_entry_is_structured_error(self) -> None:
        result = await self._execute(
            "manage_memory", {"id": 999, "action": "archive", "reason": "x"}
        )
        self.assertTrue(result.is_error)
        self.assertIn("not found", result.content)

    async def test_review_rejects_bad_scope(self) -> None:
        result = await self._execute("review_memory", {"scope": "team"})
        self.assertTrue(result.is_error)
        result = await self._execute("review_memory", {"older_than_days": -1})
        self.assertTrue(result.is_error)


class TestConfirmationFlow(_CapabilityTestCase):
    async def test_mutation_blocked_when_user_denies(self) -> None:
        denied = await self._execute(
            "remember_definition",
            {"stable_key": "k", "content": "c", "evidence": ["e"]},
            mode="default",
            confirm_fn=_permission_confirm(False),
            with_permission=True,
        )
        self.assertTrue(denied.is_error)
        self.assertIn("User denied this action.", denied.content)
        self.assertIsNone(self.store.get(1))

    async def test_mutation_allowed_after_confirmation(self) -> None:
        approved = await self._execute(
            "remember_definition",
            {"stable_key": "k", "content": "c", "evidence": ["e"]},
            mode="default",
            confirm_fn=_permission_confirm(True),
            with_permission=True,
        )
        self.assertFalse(approved.is_error, approved.content)
        self.assertIsNotNone(self.store.get(1))

    async def test_read_tools_do_not_require_confirmation(self) -> None:
        result = await self._execute(
            "recall_memory",
            {"query": "anything"},
            mode="default",
            confirm_fn=_permission_confirm(False),
            with_permission=True,
        )
        self.assertFalse(result.is_error, result.content)

    async def test_dont_ask_mode_shuts_down_on_mutation(self) -> None:
        result = await self._execute(
            "manage_memory",
            {"id": 1, "action": "purge", "reason": "x"},
            mode="dontAsk",
            with_permission=True,
        )
        self.assertTrue(result.is_error)
        self.assertTrue(result.terminate)
        self.assertTrue(result.details.get("budget_exceeded"))
        self.assertIn("Budget exceeded", result.content)


if __name__ == "__main__":
    unittest.main()
