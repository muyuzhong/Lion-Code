"""Canonical Memory store 契约测试。"""

from __future__ import annotations

import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from lion_code.capabilities.memory.store import (
    MEMORY_REVIEW_AFTER_DAYS,
    MemoryConflictError,
    MemorySchemaError,
    MemoryStore,
    MemoryValidationError,
)


class MemoryStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project_root = self.root / "project"
        self.project_root.mkdir()
        self.db_path = self.root / "memory.sqlite3"
        self.store = MemoryStore(self.db_path, project_key="project-a")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def remember_definition(self, **overrides: object):
        values: dict[str, object] = {
            "kind": "definition",
            "scope": "project",
            "stable_key": "ci-policy",
            "content": "CI must pass before merge",
            "evidence_type": "source",
            "evidence_ref": "docs/ci.md",
            "paths": (),
        }
        values.update(overrides)
        return self.store.remember(**values)  # type: ignore[arg-type]

    def remember_task(self, **overrides: object):
        values: dict[str, object] = {
            "stable_key": "memory-fix",
            "title": "Fix memory",
            "objective": "Converge the phase-one design",
            "summary": "Canonical store implemented",
            "next_action": "Run focused tests",
            "refs": ("lion_code/capabilities/memory/store.py",),
        }
        values.update(overrides)
        return self.store.remember_task(**values)  # type: ignore[arg-type]

    def test_constructor_is_lazy_and_first_open_creates_only_canonical_schema(
        self,
    ) -> None:
        self.assertFalse(self.db_path.exists())

        self.assertEqual(self.store.recall_tasks(), [])

        conn = sqlite3.connect(self.db_path)
        try:
            objects = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                )
            }
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
            semantic_columns = {
                row[1] for row in conn.execute("PRAGMA table_info(semantic_entries)")
            }
        finally:
            conn.close()
        self.assertEqual(
            objects,
            {
                "semantic_entries",
                "tasks",
                "semantic_active_stable_key",
                "task_active_stable_key",
            },
        )
        self.assertEqual(version, 1)
        self.assertEqual(journal, "wal")
        self.assertEqual(
            semantic_columns,
            {
                "id",
                "scope",
                "project_key",
                "kind",
                "stable_key",
                "content",
                "trigger",
                "pinned",
                "evidence_type",
                "evidence_ref",
                "paths_json",
                "validated_at",
                "created_at",
                "updated_at",
                "archived_at",
            },
        )

    def test_fresh_database_concurrent_first_open_is_safe(self) -> None:
        stores = [MemoryStore(self.db_path, project_key="project-a") for _ in range(8)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda store: store.recall_tasks(), stores))
        self.assertEqual(results, [[]] * 8)

    def test_unknown_or_corrupt_database_fails_closed_on_first_access(self) -> None:
        unknown = self.root / "unknown.sqlite3"
        conn = sqlite3.connect(unknown)
        conn.execute("CREATE TABLE foreign_data (value TEXT)")
        conn.execute("PRAGMA user_version = 99")
        conn.commit()
        conn.close()
        store = MemoryStore(unknown, project_key="project-a")
        with self.assertRaises(MemorySchemaError):
            store.recall_tasks()
        conn = sqlite3.connect(unknown)
        try:
            self.assertIsNotNone(
                conn.execute(
                    "SELECT name FROM sqlite_master WHERE name = 'foreign_data'"
                ).fetchone()
            )
        finally:
            conn.close()

        corrupt = self.root / "corrupt.sqlite3"
        original = b"not a sqlite database"
        corrupt.write_bytes(original)
        with self.assertRaises(MemorySchemaError):
            MemoryStore(corrupt, project_key="project-a").recall_tasks()
        self.assertEqual(corrupt.read_bytes(), original)

    def test_same_version_database_with_extra_columns_fails_closed(self) -> None:
        self.store.recall_tasks()
        conn = sqlite3.connect(self.db_path)
        conn.execute("ALTER TABLE semantic_entries ADD COLUMN source_session_id TEXT")
        conn.commit()
        conn.close()

        with self.assertRaisesRegex(MemorySchemaError, "schema columns mismatch"):
            self.store.recall_tasks()

    def test_task_ledger_supports_zero_one_many_update_and_project_isolation(
        self,
    ) -> None:
        self.assertEqual(self.store.recall_tasks(), [])
        first = self.remember_task()
        updated = self.remember_task(
            stable_key=" Memory-Fix ",
            summary="Store tests added",
            next_action="Implement tools",
            refs=(" lion_code/capabilities/memory/store.py ", "#123"),
        )
        self.assertEqual(updated.id, first.id)
        self.assertEqual(updated.stable_key, "memory-fix")
        self.assertEqual(updated.summary, "Store tests added")
        self.assertEqual(
            updated.refs, ("lion_code/capabilities/memory/store.py", "#123")
        )
        with self.assertRaises(MemoryValidationError):
            self.remember_task(refs=(" ",))

        second = self.remember_task(
            stable_key="docs",
            title="Update docs",
            summary="Not started",
            next_action="Write contract",
        )
        self.assertEqual(
            {task.id for task in self.store.recall_tasks()}, {first.id, second.id}
        )
        self.assertEqual(
            self.store.recall_tasks(stable_key="MEMORY-FIX")[0].id, first.id
        )
        other = MemoryStore(self.db_path, project_key="project-b")
        self.assertEqual(other.recall_tasks(), [])

    def test_task_lifecycle_archived_view_restore_conflict_and_purge(self) -> None:
        task = self.remember_task()
        self.assertEqual(self.store.complete_task(task.id).status, "completed")
        self.assertEqual(self.store.recall_tasks(), [])
        self.assertEqual(self.store.reopen_task(task.id).status, "open")

        archived = self.store.archive_task(task.id)
        self.assertTrue(archived.is_archived)
        self.assertEqual(self.store.archived_tasks()[0].id, task.id)
        replacement = self.remember_task(summary="Replacement active task")
        self.assertNotEqual(replacement.id, task.id)
        with self.assertRaises(MemoryConflictError):
            self.store.restore_task(task.id)
        self.store.purge_task(replacement.id)
        restored = self.store.restore_task(task.id)
        self.assertFalse(restored.is_archived)
        self.store.purge_task(task.id)
        self.assertEqual(self.store.recall_tasks(status="all"), [])

    def test_four_semantic_quadrants_and_project_isolation(self) -> None:
        entries = [
            self.store.remember(
                kind=kind,
                scope=scope,
                stable_key=f"{scope}-{kind}",
                content=f"{scope} {kind}",
                trigger="when applicable" if kind == "behavior" else None,
                evidence_type="test",
                evidence_ref="test_four_semantic_quadrants",
            )
            for scope in ("long_term", "project")
            for kind in ("definition", "behavior")
        ]
        self.assertEqual(len(entries), 4)
        other = MemoryStore(self.db_path, project_key="project-b")
        self.assertEqual(
            {entry.scope for entry in other.recall_memory("long_term")},
            {"long_term"},
        )
        self.assertEqual(other.recall_memory("project-definition"), [])

    def test_semantic_validation_and_stable_key_update(self) -> None:
        first = self.remember_definition()
        updated = self.remember_definition(
            stable_key="  CI-POLICY  ",
            content="Wait for all CI jobs",
            evidence_type="command",
            evidence_ref="gh pr checks",
            paths=(r"src\main.py", "src/main.py"),
        )
        self.assertEqual(updated.id, first.id)
        self.assertEqual(updated.content, "Wait for all CI jobs")
        self.assertEqual(updated.evidence_type, "command")
        self.assertEqual(updated.paths, ("src/main.py",))

        for bad_type in ("", "guess"):
            with self.assertRaises(MemoryValidationError):
                self.remember_definition(evidence_type=bad_type)
        with self.assertRaises(MemoryValidationError):
            self.remember_definition(evidence_ref=" ")
        with self.assertRaises(MemoryValidationError):
            self.store.remember(
                kind="behavior",
                scope="project",
                stable_key="missing-trigger",
                content="do it",
                evidence_type="test",
                evidence_ref="test",
            )
        with self.assertRaises(MemoryValidationError):
            self.remember_definition(trigger="not allowed")
        with self.assertRaises(MemoryValidationError):
            self.remember_definition(scope="long_term", paths=("src/main.py",))
        with self.assertRaises(MemoryValidationError):
            self.remember_definition(paths=("../escape.py",))
        with self.assertRaises(MemoryValidationError):
            self.remember_definition(paths=("C:escape.py",))

    def test_pinned_cannot_be_overwritten_and_archive_restore_clears_pin(self) -> None:
        entry = self.remember_definition()
        self.store.set_pinned(entry.id, pinned=True)
        with self.assertRaises(MemoryConflictError):
            self.remember_definition(content="bypass")

        archived = self.store.archive_semantic(entry.id)
        self.assertTrue(archived.is_archived)
        self.assertFalse(archived.pinned)
        restored = self.store.restore_semantic(entry.id)
        self.assertFalse(restored.is_archived)
        self.assertFalse(restored.pinned)

    def test_restore_conflict_and_archived_view_return_ids(self) -> None:
        original = self.remember_definition()
        self.store.archive_semantic(original.id)
        replacement = self.remember_definition(content="replacement")
        self.assertEqual(self.store.archived_semantic()[0].id, original.id)
        with self.assertRaises(MemoryConflictError):
            self.store.restore_semantic(original.id)
        self.store.purge_semantic(replacement.id)
        self.assertEqual(self.store.restore_semantic(original.id).id, original.id)

    def test_age_or_any_missing_path_excludes_recall_until_validate(self) -> None:
        (self.project_root / "exists.py").write_text("ok", encoding="utf-8")
        entry = self.remember_definition(paths=("exists.py", "missing.py"))
        self.store.set_pinned(entry.id, pinned=True)
        review = self.store.needs_review(project_root=self.project_root)
        self.assertEqual(review[0].entry.id, entry.id)
        self.assertIn("missing path: missing.py", review[0].reasons)
        self.assertEqual(
            self.store.recall_memory("ci-policy", project_root=self.project_root), []
        )
        self.assertEqual(self.store.pinned(project_root=self.project_root), [])
        self.assertTrue(
            any(
                "project root unavailable" in reason
                for reason in self.store.needs_review()[0].reasons
            )
        )

        conn = sqlite3.connect(self.db_path)
        old = datetime.now(UTC) - timedelta(days=MEMORY_REVIEW_AFTER_DAYS + 1)
        conn.execute(
            "UPDATE semantic_entries SET paths_json = '[]', validated_at = ? WHERE id = ?",
            (old.isoformat(), entry.id),
        )
        conn.commit()
        conn.close()
        self.assertEqual(
            len(self.store.needs_review(project_root=self.project_root)), 1
        )
        validated = self.store.validate_semantic(
            entry.id, evidence_type="test", evidence_ref="fresh validation"
        )
        self.assertEqual(validated.evidence_ref, "fresh validation")
        self.assertEqual(
            self.store.recall_memory("ci-policy", project_root=self.project_root)[0].id,
            entry.id,
        )
        self.assertEqual(
            self.store.pinned(project_root=self.project_root)[0].id,
            entry.id,
        )

    def test_literal_recall_is_bounded_and_does_not_use_fts(self) -> None:
        (self.project_root / "docs").mkdir()
        (self.project_root / "docs" / "ci.md").write_text("CI", encoding="utf-8")
        exact = self.remember_definition(stable_key="deploy-hook")
        literal = self.remember_definition(
            stable_key="merge-rule",
            content="wait for continuous integration",
            paths=("docs/ci.md",),
        )
        self.assertEqual(self.store.recall_memory("DEPLOY-HOOK")[0].id, exact.id)
        self.assertEqual(
            self.store.recall_memory(
                "continuous integration", project_root=self.project_root
            )[0].id,
            literal.id,
        )
        self.assertEqual(
            self.store.recall_memory("wait   for", project_root=self.project_root)[
                0
            ].id,
            literal.id,
        )
        self.assertEqual(
            self.store.recall_memory(r"docs\ci.md", project_root=self.project_root)[
                0
            ].id,
            literal.id,
        )


if __name__ == "__main__":
    unittest.main()
