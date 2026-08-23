"""Memory 工具、权限与静态策略测试。"""

from __future__ import annotations

import sqlite3
import unittest
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from lion_code.capabilities.memory import MemoryStore, create_memory_capability
from lion_code.context.estimator import estimate_text_tokens
from lion_code.core.cancellation import CancellationToken
from lion_code.permission_state import PermissionController, PermissionState
from lion_code.runtime.session_identity import SessionIdentityState
from lion_code.tooling.context import ToolContext
from lion_code.tooling.middleware import PermissionMiddleware
from lion_code.tooling.permission import PermissionPolicy
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.runtime import ToolRuntime
from lion_code.tooling.types import JSONValue, ToolResult

SESSION_ID = "session-1"
STARTED_AT = "2026-08-23T00:00:00Z"


class MemoryCapabilityTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project_root = self.root / "project"
        self.project_root.mkdir()
        self.db_path = self.root / "memory.sqlite3"
        self.store = MemoryStore(self.db_path, project_key="project-a")
        self.spec = create_memory_capability(self.store, project_root=self.project_root)
        self.registry = ToolRegistry()
        for source in self.spec.tool_sources:
            for tool in source.tools():
                self.registry.register(tool)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _runtime(
        self,
        *,
        mode: str = "bypassPermissions",
        confirm_fn: Any = None,
        permission_middleware: bool = False,
    ) -> ToolRuntime:
        permission = PermissionController(PermissionState(mode))  # type: ignore[arg-type]
        context = ToolContext(
            session=SessionIdentityState(SESSION_ID, STARTED_AT),
            cancellation=CancellationToken(),
            cwd=self.project_root,
            registry=self.registry,
            permission=permission,
            read_file_state={},
            confirm_fn=confirm_fn,
        )
        middleware = (
            [
                PermissionMiddleware(
                    PermissionPolicy(cwd=self.root, home=self.root), permission
                )
            ]
            if permission_middleware
            else []
        )
        return ToolRuntime(self.registry, context, middleware)

    async def execute(
        self,
        name: str,
        arguments: Mapping[str, JSONValue],
        **runtime_options: Any,
    ) -> ToolResult:
        return await self._runtime(**runtime_options).execute(
            tool_call_id="call-1", name=name, arguments=arguments
        )

    async def remember_definition(self, **overrides: JSONValue) -> ToolResult:
        arguments: dict[str, JSONValue] = {
            "stable_key": "ci-policy",
            "content": "CI must pass before merge",
            "evidence_type": "source",
            "evidence_ref": "docs/ci.md",
        }
        arguments.update(overrides)
        return await self.execute("remember_definition", arguments)

    async def remember_task(self, **overrides: JSONValue) -> ToolResult:
        arguments: dict[str, JSONValue] = {
            "stable_key": "memory-fix",
            "title": "Fix memory",
            "objective": "Converge phase one",
            "summary": "Store is ready",
            "next_action": "Implement tools",
            "refs": ["lion_code/capabilities/memory/store.py"],
        }
        arguments.update(overrides)
        return await self.execute("remember_task", arguments)

    def test_tool_shape_and_memory_policy(self) -> None:
        tools = {tool.name: tool for tool in self.registry.all_tools()}
        self.assertEqual(
            set(tools),
            {
                "remember_task",
                "recall_tasks",
                "remember_definition",
                "remember_behavior",
                "recall_memory",
                "review_memory",
                "manage_memory",
                "set_memory_pinned",
                "purge_memory",
            },
        )
        for name in ("recall_tasks", "recall_memory", "review_memory"):
            self.assertTrue(tools[name].capabilities.read_only)
            self.assertTrue(tools[name].capabilities.concurrency_safe)
            self.assertEqual(tools[name].execution_mode, "parallel")
        for name in ("set_memory_pinned", "purge_memory"):
            self.assertTrue(tools[name].capabilities.requires_confirmation)
        for name in (
            "remember_task",
            "remember_definition",
            "remember_behavior",
            "manage_memory",
        ):
            self.assertFalse(tools[name].capabilities.requires_confirmation)

        self.assertEqual(len(self.spec.prompt_layers), 1)
        policy = self.spec.prompt_layers[0].render()
        self.assertIn("call recall_tasks", policy)
        self.assertIn("significant milestone", policy)
        self.assertIn("typed evidence", policy)
        self.assertIn("never store secrets", policy)
        self.assertIn("always override Memory", policy)
        self.assertIsNone(self.spec.context_layer)
        self.assertIsNone(self.spec.query_context_layer)

    async def test_task_tool_zero_one_many_and_lifecycle(self) -> None:
        empty = await self.execute("recall_tasks", {})
        self.assertIn("No matching tasks", empty.content)
        first = await self.remember_task()
        self.assertFalse(first.is_error, first.content)
        one = await self.execute("recall_tasks", {})
        self.assertIn("One matching task", one.content)
        self.assertIn("Objective: Converge phase one", one.content)
        await self.remember_task(
            stable_key="docs",
            title="Update docs",
            summary="Not started",
            next_action="Write docs",
        )
        many = await self.execute("recall_tasks", {})
        self.assertIn("2 matching tasks; choose one", many.content)

        completed = await self.execute(
            "manage_memory", {"target": "task", "id": 1, "action": "complete"}
        )
        self.assertFalse(completed.is_error, completed.content)
        open_tasks = await self.execute("recall_tasks", {})
        self.assertNotIn("memory-fix", open_tasks.content)
        reopened = await self.execute(
            "manage_memory", {"target": "task", "id": 1, "action": "reopen"}
        )
        self.assertFalse(reopened.is_error, reopened.content)

    async def test_task_recall_has_a_fixed_text_budget(self) -> None:
        await self.remember_task(summary="progress " * 2000)

        result = await self.execute("recall_tasks", {})

        self.assertLessEqual(estimate_text_tokens(result.content), 800)
        self.assertIn("One matching task", result.content)
        self.assertIn("budgeted", result.content)

    async def test_semantic_roundtrip_uses_typed_evidence_and_defaults_unpinned(
        self,
    ) -> None:
        written = await self.remember_definition(paths=[])
        self.assertFalse(written.is_error, written.content)
        entry = self.store.get(1)
        assert entry is not None
        self.assertFalse(entry.pinned)
        self.assertEqual(entry.evidence_type, "source")
        self.assertEqual(entry.evidence_ref, "docs/ci.md")

        recalled = await self.execute("recall_memory", {"query": "ci-policy"})
        self.assertIn("Found 1 memory entries", recalled.content)
        self.assertIn("Evidence: source:docs/ci.md", recalled.content)

        behavior = await self.execute(
            "remember_behavior",
            {
                "scope": "long_term",
                "stable_key": "pr-flow",
                "trigger": "when preparing a merge",
                "instruction": "wait for CI",
                "evidence_type": "user_request",
                "evidence_ref": "user asked in session-1",
            },
        )
        self.assertFalse(behavior.is_error, behavior.content)
        recalled = await self.execute("recall_memory", {"query": "pr-flow"})
        self.assertIn("When: when preparing a merge Do: wait for CI", recalled.content)

    async def test_validate_requires_new_evidence_and_archived_views_return_ids(
        self,
    ) -> None:
        await self.remember_definition()
        missing = await self.execute(
            "manage_memory", {"target": "semantic", "id": 1, "action": "validate"}
        )
        self.assertTrue(missing.is_error)
        self.assertIn("evidence_type", missing.content)

        validated = await self.execute(
            "manage_memory",
            {
                "target": "semantic",
                "id": 1,
                "action": "validate",
                "evidence_type": "test",
                "evidence_ref": "test_validate",
            },
        )
        self.assertFalse(validated.is_error, validated.content)
        self.assertEqual(self.store.get(1).evidence_type, "test")  # type: ignore[union-attr]

        await self.execute(
            "manage_memory", {"target": "semantic", "id": 1, "action": "archive"}
        )
        semantic = await self.execute(
            "review_memory", {"view": "archived", "target": "semantic"}
        )
        self.assertIn("m:1", semantic.content)
        entries = semantic.details["entries"]
        assert isinstance(entries, list)
        entry = entries[0]
        assert isinstance(entry, dict)
        self.assertEqual(entry["id"], 1)

        await self.remember_task()
        await self.execute(
            "manage_memory", {"target": "task", "id": 1, "action": "archive"}
        )
        tasks = await self.execute(
            "review_memory", {"view": "archived", "target": "task"}
        )
        self.assertIn("t:1", tasks.content)

    async def test_needs_review_is_reported_and_excluded_from_recall(self) -> None:
        await self.remember_definition(paths=["missing.py"])
        review = await self.execute("review_memory", {"view": "needs_review"})
        self.assertIn("missing path: missing.py", review.content)
        recall = await self.execute("recall_memory", {"query": "ci-policy"})
        self.assertIn("No active, reviewed", recall.content)

        conn = sqlite3.connect(self.db_path)
        old = datetime.now(UTC) - timedelta(days=91)
        conn.execute(
            "UPDATE semantic_entries SET paths_json = '[]', validated_at = ? WHERE id = 1",
            (old.isoformat(),),
        )
        conn.commit()
        conn.close()
        review = await self.execute("review_memory", {"view": "needs_review"})
        self.assertIn("validation older than 90 days", review.content)

    async def test_pin_and_purge_use_confirmation_but_ordinary_mutations_do_not(
        self,
    ) -> None:
        confirmations: list[str] = []

        async def deny(message: str) -> bool:
            confirmations.append(message)
            return False

        ordinary = await self.execute(
            "remember_definition",
            {
                "stable_key": "k",
                "content": "c",
                "evidence_type": "test",
                "evidence_ref": "test",
            },
            mode="default",
            confirm_fn=deny,
            permission_middleware=True,
        )
        self.assertFalse(ordinary.is_error, ordinary.content)
        self.assertEqual(confirmations, [])

        pin = await self.execute(
            "set_memory_pinned",
            {"id": 1, "pinned": True},
            mode="default",
            confirm_fn=deny,
            permission_middleware=True,
        )
        self.assertTrue(pin.is_error)
        self.assertIn("User denied", pin.content)
        self.assertFalse(self.store.get(1).pinned)  # type: ignore[union-attr]
        purge = await self.execute(
            "purge_memory",
            {"target": "semantic", "id": 1},
            mode="default",
            confirm_fn=deny,
            permission_middleware=True,
        )
        self.assertTrue(purge.is_error)
        self.assertIsNotNone(self.store.get(1))

    async def test_pinned_update_and_restore_cannot_bypass_confirmation_boundary(
        self,
    ) -> None:
        await self.remember_definition()
        pinned = await self.execute("set_memory_pinned", {"id": 1, "pinned": True})
        self.assertFalse(pinned.is_error, pinned.content)
        blocked = await self.remember_definition(content="bypass")
        self.assertTrue(blocked.is_error)
        self.assertIn("must be unpinned", blocked.content)

        await self.execute(
            "manage_memory", {"target": "semantic", "id": 1, "action": "archive"}
        )
        restored = await self.execute(
            "manage_memory", {"target": "semantic", "id": 1, "action": "restore"}
        )
        self.assertFalse(restored.is_error, restored.content)
        self.assertFalse(self.store.get(1).pinned)  # type: ignore[union-attr]

    async def test_pinned_overflow_skips_large_entry_without_blocking_small_entry(
        self,
    ) -> None:
        await self.remember_definition(stable_key="a-large", content="large " * 3000)
        await self.remember_definition(stable_key="b-small", content="small rule")
        await self.execute("set_memory_pinned", {"id": 1, "pinned": True})
        await self.execute("set_memory_pinned", {"id": 2, "pinned": True})

        review = await self.execute(
            "review_memory", {"view": "pinned_overflow", "target": "semantic"}
        )
        self.assertIn("m:1 a-large", review.content)
        self.assertNotIn("m:2 b-small", review.content)

    async def test_invalid_tool_arguments_return_structured_errors(self) -> None:
        missing_evidence = await self.remember_definition(evidence_type="guess")
        self.assertTrue(missing_evidence.is_error)
        bad_action = await self.execute(
            "manage_memory", {"target": "task", "id": 1, "action": "validate"}
        )
        self.assertTrue(bad_action.is_error)
        bad_target = await self.execute("purge_memory", {"target": "session", "id": 1})
        self.assertTrue(bad_target.is_error)

    async def test_database_failure_is_a_structured_tool_result(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE foreign_data (value TEXT)")
        conn.execute("PRAGMA user_version = 99")
        conn.commit()
        conn.close()

        result = await self.execute("recall_tasks", {})

        self.assertTrue(result.is_error)
        self.assertIn(str(self.db_path), result.content)
        self.assertIn("schema version mismatch", result.content)


if __name__ == "__main__":
    unittest.main()
