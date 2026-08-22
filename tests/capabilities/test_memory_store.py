"""MemoryStore 的 schema、生命周期、检索与并发测试。

全部使用临时目录中的数据库，绝不触碰真实 ``~/.lion-code/memory.sqlite3``。
"""

from __future__ import annotations

import sqlite3
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from lion_code.capabilities.memory.store import (
    MemoryConflictError,
    MemorySchemaError,
    MemoryStore,
    MemoryValidationError,
    ReviewStaleCandidate,
    default_memory_db_path,
)


class _StoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db_path = self.root / "memory.sqlite3"
        self.project_root = self.root / "project"
        self.project_root.mkdir()
        (self.project_root / "docs").mkdir()
        (self.project_root / "docs" / "ci.md").write_text("ci", encoding="utf-8")
        self.store = MemoryStore(self.db_path, project_key="proj-a")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def remember_definition(self, **overrides: object) -> object:
        arguments: dict[str, object] = {
            "kind": "definition",
            "scope": "project",
            "stable_key": "ci-guard",
            "content": "CI must pass before merge",
            "evidence": ["docs/ci.md"],
            "paths": ["docs/ci.md"],
        }
        arguments.update(overrides)
        return self.store.remember(**arguments)  # type: ignore[arg-type]


class TestFourQuadrants(_StoreTestCase):
    def test_creates_entries_in_all_four_quadrants(self) -> None:
        long_def = self.store.remember(
            kind="definition",
            scope="long_term",
            stable_key="user-env",
            content="Python 3.12 on Windows with Git Bash",
            evidence=["session observation"],
        )
        proj_def = self.remember_definition()
        long_beh = self.store.remember(
            kind="behavior",
            scope="long_term",
            stable_key="pr-flow",
            trigger="when merging a PR",
            content="wait for CI green",
            evidence=["AGENTS.md"],
        )
        proj_beh = self.store.remember(
            kind="behavior",
            scope="project",
            stable_key="ci-guard-behavior",
            trigger="before merge",
            content="run full pytest suite",
            evidence=["docs/ci.md"],
        )
        for entry, scope, kind in (
            (long_def, "long_term", "definition"),
            (proj_def, "project", "definition"),
            (long_beh, "long_term", "behavior"),
            (proj_beh, "project", "behavior"),
        ):
            self.assertEqual(entry.scope, scope)
            self.assertEqual(entry.kind, kind)
            self.assertEqual(entry.status, "active")
            self.assertEqual(entry.recall_mode, "relevant")
        self.assertIsNone(long_def.project_key)
        self.assertEqual(proj_def.project_key, "proj-a")
        self.assertIsNone(long_def.trigger)
        self.assertEqual(long_beh.trigger, "when merging a PR")
        self.assertEqual(long_def.display_path(), "long_term/definition")
        self.assertEqual(proj_beh.display_path(), "proj-a/behavior")

    def test_project_key_hard_isolation_between_projects(self) -> None:
        self.remember_definition(stable_key="shared-key")
        other = MemoryStore(self.db_path, project_key="proj-b")
        other.remember(
            kind="definition",
            scope="project",
            stable_key="shared-key",
            content="different project fact",
            evidence=["b"],
        )
        # 检索、读取、review、manage 都看不到对方 project 的条目
        self.assertEqual(
            [hit.entry.stable_key for hit in self.store.search("shared-key project")],
            ["shared-key"],
        )
        other_entry = other.search("shared-key project")[0].entry
        self.assertIsNone(self.store.get(other_entry.id))
        with self.assertRaises(MemoryConflictError):
            self.store.manage(other_entry.id, "archive", reason="x")
        report = self.store.review("all")
        self.assertEqual(report.archived_count, 0)
        # 同名 stable key 在两个 project 各自持有 active revision
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT project_key FROM memory_entries WHERE stable_key = ? "
                "AND status = 'active'",
                ("shared-key",),
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(sorted(str(row[0]) for row in rows), ["proj-a", "proj-b"])

    def test_long_term_entries_are_shared_across_projects(self) -> None:
        shared = self.store.remember(
            kind="definition",
            scope="long_term",
            stable_key="user-env",
            content="user prefers concise answers",
            evidence=["feedback"],
        )
        other = MemoryStore(self.db_path, project_key="proj-b")
        hits = other.search("concise answers")
        self.assertEqual([hit.entry.id for hit in hits], [shared.id])
        restored = other.manage(shared.id, "validate")
        self.assertIsNotNone(restored)


class TestSchemaInitialization(_StoreTestCase):
    def test_initializes_wal_and_expected_tables(self) -> None:
        conn = sqlite3.connect(self.db_path)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            objects = {
                str(row[0])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
                )
            }
            version = conn.execute(
                "SELECT value FROM memory_meta WHERE key = 'schema_version'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(str(mode).lower(), "wal")
        self.assertEqual(version, "1")
        self.assertIn("memory_entries", objects)
        self.assertIn("memory_fts", objects)
        self.assertIn("memory_active_stable_key", objects)

    def test_corrupt_database_fails_closed_without_overwriting(self) -> None:
        garbage = b"this is definitely not a sqlite database" * 10
        self.db_path.write_bytes(garbage)
        with self.assertRaises(MemorySchemaError):
            MemoryStore(self.db_path, project_key="proj-a")
        self.assertEqual(self.db_path.read_bytes(), garbage)

    def test_unwritable_db_path_fails_closed(self) -> None:
        # 目录不是可打开的数据库文件：connect 即失败，不创建不覆盖
        with self.assertRaises(MemorySchemaError) as ctx:
            MemoryStore(self.root, project_key="proj-a")
        self.assertIn("cannot open memory database", str(ctx.exception))

    def test_foreign_key_violation_fails_closed(self) -> None:
        self.remember_definition()
        # 绕过 FK 的原始写入（sqlite3 默认 foreign_keys=OFF）模拟历史损坏
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO memory_entries (scope, project_key, kind, "
                "stable_key, content, trigger, recall_mode, status, "
                "evidence_json, paths_json, created_at, updated_at, "
                "supersedes_id) VALUES ('long_term', NULL, 'definition', "
                "'orphan', 'c', NULL, 'relevant', 'active', '[\"e\"]', '[]', "
                "'t', 't', 424242)"
            )
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(MemorySchemaError) as ctx:
            MemoryStore(self.db_path, project_key="proj-a")
        self.assertIn("foreign key check failed", str(ctx.exception))

    def test_corrupt_pages_fail_closed(self) -> None:
        self.remember_definition()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA writable_schema=ON")
            conn.execute(
                "UPDATE sqlite_master SET rootpage=999999 WHERE name='memory_entries'"
            )
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(MemorySchemaError):
            MemoryStore(self.db_path, project_key="proj-a")

    def test_schema_version_mismatch_fails_closed_and_keeps_data(self) -> None:
        self.remember_definition()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE memory_meta SET value = '99' WHERE key = 'schema_version'"
            )
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(MemorySchemaError) as ctx:
            MemoryStore(self.db_path, project_key="proj-a")
        self.assertIn("version mismatch", str(ctx.exception))
        conn = sqlite3.connect(self.db_path)
        try:
            count = conn.execute("SELECT count(*) FROM memory_entries").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 1)

    def test_missing_schema_version_row_fails_closed(self) -> None:
        self.remember_definition()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("DELETE FROM memory_meta WHERE key = 'schema_version'")
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(MemorySchemaError):
            MemoryStore(self.db_path, project_key="proj-a")

    def test_missing_expected_object_fails_closed(self) -> None:
        self.remember_definition()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("DROP TABLE memory_fts")
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(MemorySchemaError) as ctx:
            MemoryStore(self.db_path, project_key="proj-a")
        self.assertIn("missing expected objects", str(ctx.exception))

    def test_empty_project_key_rejected(self) -> None:
        with self.assertRaises(MemoryValidationError):
            MemoryStore(self.db_path, project_key="")

    def test_existing_store_reopens_with_same_data(self) -> None:
        entry = self.remember_definition()
        reopened = MemoryStore(self.db_path, project_key="proj-a")
        self.assertEqual(reopened.project_key, "proj-a")
        self.assertEqual(reopened.db_path, self.db_path)
        fetched = reopened.get(entry.id)
        self.assertIsNotNone(fetched)
        assert fetched is not None
        self.assertEqual(fetched.stable_key, entry.stable_key)

    def test_default_memory_db_path_is_under_user_home(self) -> None:
        path = default_memory_db_path()
        self.assertEqual(path.name, "memory.sqlite3")
        self.assertEqual(path.parent.name, ".lion-code")


class TestWriteConstraints(_StoreTestCase):
    def test_long_term_with_paths_rejected_by_check_constraint(self) -> None:
        with self.assertRaises(MemoryValidationError):
            self.store.remember(
                kind="definition",
                scope="long_term",
                stable_key="user-env",
                content="fact",
                evidence=["e"],
                paths=["docs/ci.md"],
            )

    def test_behavior_requires_trigger(self) -> None:
        with self.assertRaises(MemoryValidationError):
            self.store.remember(
                kind="behavior",
                scope="project",
                stable_key="no-trigger",
                content="do things",
                evidence=["e"],
            )

    def test_definition_rejects_trigger(self) -> None:
        with self.assertRaises(MemoryValidationError):
            self.store.remember(
                kind="definition",
                scope="project",
                stable_key="with-trigger",
                content="fact",
                evidence=["e"],
                trigger="when",
            )

    def test_empty_evidence_rejected(self) -> None:
        with self.assertRaises(MemoryValidationError):
            self.store.remember(
                kind="definition",
                scope="project",
                stable_key="no-evidence",
                content="fact",
                evidence=[],
            )
        with self.assertRaises(MemoryValidationError):
            self.store.remember(
                kind="definition",
                scope="project",
                stable_key="no-evidence",
                content="fact",
                evidence=["  "],
            )

    def test_invalid_enums_rejected(self) -> None:
        for overrides in (
            {"scope": "team"},
            {"kind": "note"},
            {"recall_mode": "always"},
        ):
            with self.assertRaises(MemoryValidationError):
                self.remember_definition(**overrides)

    def test_blank_content_and_key_rejected(self) -> None:
        with self.assertRaises(MemoryValidationError):
            self.remember_definition(stable_key="  ")
        with self.assertRaises(MemoryValidationError):
            self.remember_definition(content=" ")

    def test_invalid_paths_rejected(self) -> None:
        with self.assertRaises(MemoryValidationError):
            self.remember_definition(paths=[str(self.root / "abs.md")])
        with self.assertRaises(MemoryValidationError):
            self.remember_definition(paths=["../escape.md"])
        with self.assertRaises(MemoryValidationError):
            self.remember_definition(paths=[" untrimmed.md "])

    def test_active_stable_key_uniqueness_enforced_at_store_level(self) -> None:
        self.remember_definition()
        conn = sqlite3.connect(self.db_path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO memory_entries (scope, project_key, kind, "
                    "stable_key, content, trigger, recall_mode, status, "
                    "evidence_json, paths_json, created_at, updated_at) "
                    "VALUES ('project', 'proj-a', 'definition', 'ci-guard', "
                    "'dup', NULL, 'relevant', 'active', '[\"e\"]', '[]', "
                    "'2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
                )
        finally:
            conn.close()

    def test_unique_index_race_surfaces_as_validation_error(self) -> None:
        # 模拟「读到无 active → 另一写者抢先插入同 key」的竞态：
        # 唯一索引拦截，IntegrityError 转为 MemoryValidationError
        self.remember_definition()
        with patch.object(MemoryStore, "_active_row", return_value=None):
            with self.assertRaises(MemoryValidationError) as ctx:
                self.remember_definition(content="race loser")
        self.assertIn("constraint rejected write", str(ctx.exception))
        kept = self.store.get(1)
        assert kept is not None
        self.assertEqual(kept.content, "CI must pass before merge")

    def test_inserted_revision_disappearing_raises_conflict(self) -> None:
        # INSERT 成功但回读为空的防御路径：事务回滚，不留半写状态
        with patch.object(MemoryStore, "_active_row", return_value=None):
            with self.assertRaises(MemoryConflictError):
                self.remember_definition()
        self.assertIsNone(self.store.get(1))


class TestRevisionLifecycle(_StoreTestCase):
    def test_remember_same_key_supersedes_previous_revision(self) -> None:
        first = self.remember_definition()
        second = self.remember_definition(
            content="CI must pass before merge, including ruff"
        )
        old = self.store.get(first.id)
        assert old is not None
        self.assertEqual(old.status, "archived")
        self.assertEqual(old.archived_reason, "superseded")
        self.assertEqual(second.supersedes_id, first.id)
        self.assertEqual(second.status, "active")

    def test_three_revision_chain(self) -> None:
        first = self.remember_definition()
        second = self.remember_definition(content="v2")
        third = self.remember_definition(content="v3")
        self.assertEqual(third.supersedes_id, second.id)
        self.assertEqual(second.supersedes_id, first.id)
        report = self.store.review("all", project_root=self.project_root)
        self.assertEqual(len(report.revision_chains), 1)
        chain = report.revision_chains[0]
        self.assertEqual(chain.active_id, third.id)
        self.assertEqual(chain.superseded_ids, (second.id, first.id))
        self.assertEqual(report.archived_count, 2)

    def test_mark_stale_and_restore(self) -> None:
        entry = self.remember_definition()
        stale = self.store.manage(entry.id, "mark_stale", reason="paths outdated")
        assert stale is not None
        self.assertEqual(stale.status, "stale")
        self.assertEqual(stale.archived_reason, "paths outdated")
        # stale 仍在 FTS 中，include_inactive 可检索
        self.assertEqual(self.store.search("ci merge"), [])
        hit = self.store.search("ci merge", include_inactive=True)
        self.assertEqual([h.entry.id for h in hit], [entry.id])
        restored = self.store.manage(entry.id, "restore")
        assert restored is not None
        self.assertEqual(restored.status, "active")
        self.assertIsNone(restored.archived_reason)
        self.assertEqual(
            [h.entry.id for h in self.store.search("ci merge")], [entry.id]
        )

    def test_archive_removes_from_fts_and_restore_reindexes(self) -> None:
        entry = self.remember_definition()
        archived = self.store.manage(entry.id, "archive", reason="cleanup")
        assert archived is not None
        self.assertEqual(archived.status, "archived")
        self.assertEqual(self.store.search("ci merge"), [])
        self.assertEqual(self.store.search("ci merge", include_inactive=True), [])
        restored = self.store.manage(entry.id, "restore")
        assert restored is not None
        self.assertEqual(restored.status, "active")
        self.assertEqual(
            [h.entry.id for h in self.store.search("ci merge")], [entry.id]
        )

    def test_restore_conflicts_with_newer_active_revision(self) -> None:
        first = self.remember_definition()
        second = self.remember_definition(content="v2")
        with self.assertRaises(MemoryConflictError):
            self.store.manage(first.id, "restore")
        marked = self.store.manage(second.id, "mark_stale", reason="wrong")
        assert marked is not None
        self.assertEqual(marked.status, "stale")
        restored = self.store.manage(first.id, "restore")
        assert restored is not None
        self.assertEqual(restored.status, "active")

    def test_restore_active_revision_is_noop(self) -> None:
        entry = self.remember_definition()
        restored = self.store.manage(entry.id, "restore")
        assert restored is not None
        self.assertEqual(restored.status, "active")

    def test_validate_updates_validated_at(self) -> None:
        entry = self.remember_definition()
        time.sleep(0.01)
        validated = self.store.manage(entry.id, "validate")
        assert validated is not None
        self.assertGreater(validated.validated_at, entry.created_at)

    def test_purge_physically_deletes_revision(self) -> None:
        entry = self.remember_definition()
        result = self.store.manage(entry.id, "purge", reason="wrong fact")
        self.assertIsNone(result)
        self.assertIsNone(self.store.get(entry.id))
        self.assertEqual(self.store.search("ci merge"), [])
        conn = sqlite3.connect(self.db_path)
        try:
            count = conn.execute(
                "SELECT count(*) FROM memory_entries WHERE id = ?", (entry.id,)
            ).fetchone()[0]
            fts_count = conn.execute(
                "SELECT count(*) FROM memory_fts WHERE rowid = ?", (entry.id,)
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 0)
        self.assertEqual(fts_count, 0)

    def test_purge_middle_revision_keeps_chain_via_set_null(self) -> None:
        self.remember_definition()
        second = self.remember_definition(content="v2")
        third = self.remember_definition(content="v3")
        self.store.manage(second.id, "purge", reason="remove middle")
        remaining = self.store.get(third.id)
        assert remaining is not None
        self.assertIsNone(remaining.supersedes_id)

    def test_manage_requires_reason_for_destructive_actions(self) -> None:
        entry = self.remember_definition()
        for action in ("mark_stale", "archive", "purge"):
            with self.assertRaises(MemoryValidationError):
                self.store.manage(entry.id, action, reason=None)
            with self.assertRaises(MemoryValidationError):
                self.store.manage(entry.id, action, reason="  ")

    def test_manage_rejects_unknown_action_and_unknown_id(self) -> None:
        entry = self.remember_definition()
        with self.assertRaises(MemoryValidationError):
            self.store.manage(entry.id, "delete", reason="x")
        with self.assertRaises(MemoryConflictError):
            self.store.manage(999999, "archive", reason="x")


class TestSearchPipeline(_StoreTestCase):
    def test_exact_stable_key_hit_outranks_content_hit(self) -> None:
        self.remember_definition(stable_key="deploy-hooks")
        self.remember_definition(
            stable_key="other-key",
            content="deploy hooks run after the release pipeline",
        )
        hits = self.store.search("deploy-hooks")
        self.assertEqual(hits[0].entry.stable_key, "deploy-hooks")
        self.assertGreater(hits[0].score, hits[1].score)

    def test_exact_path_hit_gets_boost(self) -> None:
        self.remember_definition(
            stable_key="keyed-path", content="release notes location"
        )
        self.remember_definition(
            stable_key="notes",
            content="release notes live in docs/releases.md",
            paths=["docs/releases.md"],
        )
        hits = self.store.search("docs/releases.md")
        self.assertEqual(hits[0].entry.stable_key, "notes")

    def test_status_hard_filter_excludes_non_active(self) -> None:
        entry = self.remember_definition()
        self.store.manage(entry.id, "mark_stale", reason="old")
        self.assertEqual(self.store.search("ci merge"), [])
        hits = self.store.search("ci merge", include_inactive=True)
        self.assertEqual([h.entry.id for h in hits], [entry.id])

    def test_top_k_trims_results(self) -> None:
        for index in range(8):
            self.remember_definition(
                stable_key=f"docker-{index}",
                content=f"docker compose service {index}",
                evidence=["e"],
            )
        hits = self.store.search("docker compose service", top_k=3)
        self.assertEqual(len(hits), 3)
        self.assertTrue(all("docker" in h.entry.stable_key for h in hits))

    def test_stable_tie_break_by_id(self) -> None:
        self.remember_definition(
            stable_key="alpha", content="shared release pipeline note", evidence=["e"]
        )
        self.remember_definition(
            stable_key="beta", content="shared release pipeline note", evidence=["e"]
        )
        hits = self.store.search("shared release pipeline")
        self.assertEqual(len(hits), 2)
        self.assertEqual([h.entry.id for h in hits], sorted(h.entry.id for h in hits))

    def test_minimum_lexical_gate_filters_diacritic_only_match(self) -> None:
        # FTS unicode61 默认折叠变音符，"cafe" 能命中 "café"；
        # lexical 门槛用字面词边界匹配，判其为 0 hit 并过滤
        self.remember_definition(
            stable_key="coffee", content="café au lait", evidence=["e"]
        )
        self.assertEqual(self.store.search("cafe"), [])

    def test_short_or_empty_query_returns_nothing(self) -> None:
        self.remember_definition()
        self.assertEqual(self.store.search(""), [])
        self.assertEqual(self.store.search("a"), [])
        self.assertEqual(self.store.search("!!"), [])


class TestReview(_StoreTestCase):
    def test_review_reports_stale_and_candidates(self) -> None:
        self.remember_definition(stable_key="healthy")
        # active 且 paths 全部失效 → stale candidate（不自动改库）
        dead = self.remember_definition(
            stable_key="dead-path",
            content="legacy module location",
            evidence=["src/legacy.py"],
            paths=["src/legacy.py"],
        )
        # 用户确认 mark_stale 后才进入 stale 列表
        marked = self.remember_definition(stable_key="marked")
        self.store.manage(marked.id, "mark_stale", reason="paths gone")
        report = self.store.review("all", project_root=self.project_root)
        self.assertEqual([entry.id for entry in report.stale], [marked.id])
        candidates = report.stale_candidates
        assert isinstance(candidates, tuple)
        self.assertEqual(
            [(c.entry_id, c.missing_paths) for c in candidates],
            [(dead.id, ("src/legacy.py",))],
        )
        # dead 仍是 active：候选只提示，状态未被自动修改
        still_active = self.store.get(dead.id)
        assert still_active is not None
        self.assertEqual(still_active.status, "active")
        # 新写入的条目 validated_at=now，不会被判为长期未验证
        self.assertEqual(report.long_unvalidated, ())

    def test_partial_path_failure_is_not_a_stale_candidate(self) -> None:
        self.remember_definition(
            stable_key="mixed",
            content="module and docs",
            evidence=["e"],
            paths=["src/legacy.py", "docs/ci.md"],
        )
        report = self.store.review("all", project_root=self.project_root)
        self.assertEqual(report.stale_candidates, ())

    def test_no_project_root_disables_candidate_computation(self) -> None:
        self.remember_definition(paths=["src/missing.py"])
        report = self.store.review("all")
        self.assertEqual(report.stale_candidates, ())

    def test_long_unvalidated_uses_cutoff(self) -> None:
        entry = self.remember_definition()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE memory_entries SET validated_at = ? WHERE id = ?",
                ("2020-01-01T00:00:00+00:00", entry.id),
            )
            conn.commit()
        finally:
            conn.close()
        fresh = self.store.review("all", older_than_days=90)
        self.assertEqual([e.id for e in fresh.long_unvalidated], [entry.id])
        ancient = self.store.review("all", older_than_days=36500)
        self.assertEqual(ancient.long_unvalidated, ())

    def test_unvalidated_falls_back_to_created_at(self) -> None:
        entry = self.remember_definition()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE memory_entries SET validated_at = NULL, created_at = ? "
                "WHERE id = ?",
                ("2020-01-01T00:00:00+00:00", entry.id),
            )
            conn.commit()
        finally:
            conn.close()
        report = self.store.review("all", older_than_days=90)
        self.assertIn(entry.id, [e.id for e in report.long_unvalidated])

    def test_unparsable_timestamps_count_as_unvalidated(self) -> None:
        entry = self.remember_definition()
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE memory_entries SET validated_at = ?, created_at = ? "
                "WHERE id = ?",
                ("garbage", "also-garbage", entry.id),
            )
            conn.commit()
        finally:
            conn.close()
        report = self.store.review("all", older_than_days=90)
        self.assertIn(entry.id, [e.id for e in report.long_unvalidated])

    def test_pinned_overflow_flagged_over_budget(self) -> None:
        self.store.remember(
            kind="behavior",
            scope="long_term",
            stable_key="big-pinned",
            trigger="always",
            content="x" * 4000,
            evidence=["e"],
            recall_mode="pinned",
        )
        self.store.remember(
            kind="definition",
            scope="long_term",
            stable_key="small-pinned",
            content="short",
            evidence=["e"],
            recall_mode="pinned",
        )
        report = self.store.review("all")
        self.assertGreater(report.pinned_tokens, report.pinned_token_budget)
        self.assertEqual(
            [e.stable_key for e in report.pinned_overflow],
            ["big-pinned", "small-pinned"],
        )

    def test_pinned_within_budget_not_flagged(self) -> None:
        self.store.remember(
            kind="behavior",
            scope="long_term",
            stable_key="small-pinned",
            trigger="always",
            content="short",
            evidence=["e"],
            recall_mode="pinned",
        )
        report = self.store.review("all")
        self.assertEqual(report.pinned_overflow, ())
        self.assertLessEqual(report.pinned_tokens, report.pinned_token_budget)

    def test_review_scope_filter(self) -> None:
        proj_entry = self.remember_definition()
        long_entry = self.store.remember(
            kind="definition",
            scope="long_term",
            stable_key="user-env",
            content="global user fact",
            evidence=["e"],
        )
        MemoryStore(self.db_path, project_key="proj-b").remember(
            kind="definition",
            scope="project",
            stable_key="b-only",
            content="other project fact",
            evidence=["e"],
        )
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE memory_entries SET validated_at = ? "
                "WHERE stable_key IN ('ci-guard', 'user-env')",
                ("2020-01-01T00:00:00+00:00",),
            )
            conn.commit()
        finally:
            conn.close()
        keys_all = {e.stable_key for e in self.store.review("all").long_unvalidated}
        keys_long = {
            e.stable_key for e in self.store.review("long_term").long_unvalidated
        }
        keys_project = {
            e.stable_key for e in self.store.review("project").long_unvalidated
        }
        self.assertEqual(keys_all, {"ci-guard", "user-env"})
        self.assertEqual(keys_long, {"user-env"})
        self.assertEqual(keys_project, {"ci-guard"})
        self.assertEqual(long_entry.scope, "long_term")
        self.assertEqual(proj_entry.scope, "project")

    def test_review_rejects_invalid_arguments(self) -> None:
        with self.assertRaises(MemoryValidationError):
            self.store.review("team")
        with self.assertRaises(MemoryValidationError):
            self.store.review("all", older_than_days=-1)


class TestPathHealthPartition(_StoreTestCase):
    def test_partition_by_path_health(self) -> None:
        healthy = self.remember_definition(stable_key="healthy")
        dead = self.remember_definition(
            stable_key="dead",
            content="legacy",
            evidence=["src/legacy.py"],
            paths=["src/legacy.py"],
        )
        partial = self.remember_definition(
            stable_key="partial",
            content="mixed",
            evidence=["e"],
            paths=["src/legacy.py", "docs/ci.md"],
        )
        entries, candidates = MemoryStore.partition_by_path_health(
            [healthy, dead, partial], self.project_root
        )
        self.assertEqual([e.stable_key for e in entries], ["healthy", "partial"])
        self.assertEqual([c.entry_id for c in candidates], [dead.id])
        self.assertIsInstance(candidates[0], ReviewStaleCandidate)
        no_root_entries, no_root_candidates = MemoryStore.partition_by_path_health(
            [dead], None
        )
        self.assertEqual([e.id for e in no_root_entries], [dead.id])
        self.assertEqual(no_root_candidates, [])


class TestConcurrency(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db_path = self.root / "memory.sqlite3"
        self.store = MemoryStore(self.db_path, project_key="proj-a")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_reader_sees_snapshot_during_write_transaction(self) -> None:
        first = self.store.remember(
            kind="definition",
            scope="project",
            stable_key="first",
            content="first entry about docker",
            evidence=["e"],
        )
        in_transaction = threading.Event()
        release = threading.Event()

        def hold_write_lock() -> None:
            conn = sqlite3.connect(self.db_path, isolation_level=None)
            try:
                conn.execute("BEGIN IMMEDIATE")
                in_transaction.set()
                release.wait(timeout=5)
                conn.execute("ROLLBACK")
            finally:
                conn.close()

        writer = threading.Thread(target=hold_write_lock)
        writer.start()
        try:
            self.assertTrue(in_transaction.wait(timeout=5))
            # 写事务持锁期间读者仍能读到旧快照（WAL + busy timeout）
            hits = self.store.search("docker")
            self.assertEqual([h.entry.id for h in hits], [first.id])
        finally:
            release.set()
            writer.join(timeout=5)

    def test_concurrent_writers_all_commit_with_busy_timeout(self) -> None:
        errors: list[Exception] = []

        def writer(index: int) -> None:
            store = MemoryStore(self.db_path, project_key="proj-a")
            try:
                for step in range(3):
                    store.remember(
                        kind="definition",
                        scope="project",
                        stable_key=f"writer-{index}-{step}",
                        content=f"entry from writer {index} step {step}",
                        evidence=["e"],
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertEqual(errors, [])
        conn = sqlite3.connect(self.db_path)
        try:
            count = conn.execute("SELECT count(*) FROM memory_entries").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 12)

    def test_concurrent_same_key_supersede_keeps_single_active(self) -> None:
        errors: list[Exception] = []

        def writer(index: int) -> None:
            store = MemoryStore(self.db_path, project_key="proj-a")
            try:
                store.remember(
                    kind="definition",
                    scope="project",
                    stable_key="contended",
                    content=f"revision from writer {index}",
                    evidence=["e"],
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)
        self.assertEqual(errors, [])
        conn = sqlite3.connect(self.db_path)
        try:
            active = conn.execute(
                "SELECT count(*) FROM memory_entries "
                "WHERE stable_key = 'contended' AND status = 'active'"
            ).fetchone()[0]
            total = conn.execute(
                "SELECT count(*) FROM memory_entries WHERE stable_key = 'contended'"
            ).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(active, 1)
        self.assertEqual(total, 4)


if __name__ == "__main__":
    unittest.main()
