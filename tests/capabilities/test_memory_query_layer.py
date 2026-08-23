"""Memory QueryContextLayer 测试：pinned/relevant 分区、预算与防串扰。

全部使用临时目录中的数据库与 project root，绝不触碰真实
``~/.lion-code/memory.sqlite3``。
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from lion_code.capabilities.memory import (
    AUTHORITY_NOTE,
    MemoryQueryContextLayer,
    MemoryStore,
    create_memory_capability,
)
from lion_code.capabilities.memory.rendering import entry_line
from lion_code.capabilities.memory.store import (
    DEFAULT_TOP_K,
    PINNED_TOKEN_BUDGET,
    TOTAL_TOKEN_BUDGET,
)
from lion_code.context.estimator import estimate_text_tokens
from lion_code.context.types import ContextView


def _view() -> ContextView:
    return ContextView.from_messages([], current_time="now")


class _LayerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db_path = self.root / "memory.sqlite3"
        self.project_root = self.root / "project"
        self.project_root.mkdir()
        (self.project_root / "src").mkdir()
        (self.project_root / "src" / "db.py").write_text("db", encoding="utf-8")
        self.store = MemoryStore(self.db_path, project_key="proj-a")
        self.layer = MemoryQueryContextLayer(self.store, project_root=self.project_root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def remember(self, **kwargs) -> None:
        # store 参数名是 content；behavior 用 instruction 表达更直观
        if "instruction" in kwargs:
            kwargs["content"] = kwargs.pop("instruction")
        self.store.remember(evidence=["evidence-source"], **kwargs)

    def pinned_lines(self, rendered: str) -> list[str]:
        sections = rendered.split("## ")
        for section in sections:
            if section.startswith("Pinned"):
                return [
                    line
                    for line in section.splitlines()[1:]
                    if line.startswith("- [m:")
                ]
        return []

    def relevant_ids(self, rendered: str) -> list[str]:
        return [
            line.split("]")[0]
            for line in rendered.splitlines()
            if line.startswith("- [m:") and "Pinned" not in line
        ]


class TestPinnedRecall(_LayerTestCase):
    def test_pinned_long_term_and_project_render_every_request(self) -> None:
        self.remember(
            kind="behavior",
            scope="long_term",
            stable_key="pr-flow",
            trigger="when merging a PR",
            instruction="wait for CI green before merge",
            recall_mode="pinned",
        )
        self.remember(
            kind="behavior",
            scope="project",
            stable_key="local-ci",
            trigger="before push",
            instruction="run the local quality gates",
            recall_mode="pinned",
        )

        rendered = self.layer.render("anything unrelated", _view())
        again = self.layer.render("another unrelated query", _view())

        self.assertTrue(rendered.startswith("# Active Memory"))
        self.assertIn("## Pinned Behaviors", rendered)
        self.assertIn("[m:1 long_term/behavior] pr-flow", rendered)
        self.assertIn("[m:2 proj-a/behavior] local-ci", rendered)
        self.assertIn("When: when merging a PR Do: wait for CI green", rendered)
        self.assertIn("Evidence: evidence-source", rendered)
        # pinned 每次 Provider request 渲染，与 query 是否相关无关
        self.assertIn("Pinned Behaviors", again)

    def test_pinned_definitions_get_their_own_section(self) -> None:
        self.remember(
            kind="definition",
            scope="long_term",
            stable_key="term-glossary",
            content="widget means the TUI panel",
            recall_mode="pinned",
        )
        rendered = self.layer.render("", _view())
        self.assertIn("## Pinned Definitions", rendered)
        self.assertIn("[m:1 long_term/definition] term-glossary", rendered)

    def test_pinned_truncation_prefers_project_behavior_and_stable_key(self) -> None:
        # project behavior 按 stable_key 升序先保留；long_term 大条目溢出被截断
        self.remember(
            kind="behavior",
            scope="project",
            stable_key="a-project",
            trigger="t",
            instruction="earlier stable key kept " * 20,
            recall_mode="pinned",
        )
        self.remember(
            kind="behavior",
            scope="project",
            stable_key="b-project",
            trigger="t",
            instruction="project behavior kept " * 20,
            recall_mode="pinned",
        )
        self.remember(
            kind="definition",
            scope="long_term",
            stable_key="z-long",
            content="long term filler " * 90,
            recall_mode="pinned",
        )

        rendered = self.layer.render("", _view())
        lines = self.pinned_lines(rendered)
        kept_keys = [line.split("] ")[1].split(":")[0] for line in lines]
        self.assertEqual(kept_keys, ["a-project", "b-project"])
        self.assertNotIn("z-long", rendered)
        used = sum(estimate_text_tokens(line) for line in lines)
        self.assertLessEqual(used, PINNED_TOKEN_BUDGET)

    def test_pinned_truncation_is_deterministic(self) -> None:
        for index in range(8):
            self.remember(
                kind="behavior",
                scope="long_term",
                stable_key=f"key-{index:02d}",
                trigger="t",
                instruction="behavior body " * 30,
                recall_mode="pinned",
            )
        first = self.layer.render("", _view())
        second = self.layer.render("", _view())
        self.assertEqual(first, second)

    def test_single_oversized_pinned_entry_is_dropped_not_injected(self) -> None:
        """单条超预算的 pinned 不整体注入：硬预算优先于非空渲染。"""
        self.remember(
            kind="behavior",
            scope="long_term",
            stable_key="giant",
            trigger="t",
            instruction="huge pinned instruction " * 400,
            recall_mode="pinned",
        )
        self.assertEqual(self.layer.render("", _view()), "")

    def test_pinned_excludes_other_projects_and_inactive(self) -> None:
        other = MemoryStore(self.db_path, project_key="proj-b")
        other.remember(
            kind="behavior",
            scope="project",
            stable_key="foreign",
            trigger="t",
            content="other project pinned",
            evidence=["evidence-source"],
            recall_mode="pinned",
        )
        self.remember(
            kind="behavior",
            scope="project",
            stable_key="archived-one",
            trigger="t",
            instruction="then archived",
            recall_mode="pinned",
        )
        self.store.manage(2, "archive", reason="cleanup")
        self.remember(
            kind="behavior",
            scope="project",
            stable_key="stale-one",
            trigger="t",
            instruction="then marked stale",
            recall_mode="pinned",
        )
        self.store.manage(3, "mark_stale", reason="old")

        rendered = self.layer.render("", _view())

        self.assertNotIn("foreign", rendered)
        self.assertNotIn("archived-one", rendered)
        self.assertNotIn("stale-one", rendered)


class TestRelevantRecall(_LayerTestCase):
    def test_relevant_definitions_and_behaviors_by_query(self) -> None:
        self.remember(
            kind="definition",
            scope="project",
            stable_key="db-paths",
            content="database paths are configured in src/db.py",
            paths=["src/db.py"],
        )
        self.remember(
            kind="behavior",
            scope="long_term",
            stable_key="db-migration",
            trigger="when changing the database schema",
            instruction="write a migration note first",
        )

        rendered = self.layer.render(
            "how are database paths configured for migration?", _view()
        )

        self.assertIn("## Relevant Definitions", rendered)
        self.assertIn("[m:1 proj-a/definition] db-paths", rendered)
        self.assertIn("Paths: src/db.py", rendered)
        self.assertIn("## Relevant Behaviors", rendered)
        self.assertIn("[m:2 long_term/behavior] db-migration", rendered)
        # 分区顺序：definitions 在 behaviors 之前
        self.assertLess(
            rendered.index("## Relevant Definitions"),
            rendered.index("## Relevant Behaviors"),
        )

    def test_unrelated_query_does_not_recall_database_memory(self) -> None:
        """防串扰：前端任务不召回数据库路径记忆（真实 FTS 过滤）。"""
        self.remember(
            kind="definition",
            scope="project",
            stable_key="db-paths",
            content="database paths are configured in src/db.py",
            paths=["src/db.py"],
        )

        rendered = self.layer.render(
            "center the login button with flexbox styling", _view()
        )

        self.assertNotIn("db-paths", rendered)
        self.assertNotIn("Relevant", rendered)
        self.assertEqual(rendered, "")

    def test_relevant_caps_at_top_k(self) -> None:
        for index in range(DEFAULT_TOP_K + 3):
            self.remember(
                kind="definition",
                scope="project",
                stable_key=f"docker-note-{index}",
                content=f"docker compose service number {index}",
            )

        rendered = self.layer.render("docker compose services", _view())

        ids = [
            int(line.split("[m:")[1].split(" ")[0])
            for line in rendered.splitlines()
            if line.startswith("- [m:")
        ]
        self.assertEqual(len(ids), DEFAULT_TOP_K)

    def test_relevant_budget_truncation_with_total_cap(self) -> None:
        for index in range(6):
            self.remember(
                kind="definition",
                scope="project",
                stable_key=f"budget-{index}",
                content="docker compose notes " * 120,
            )
        self.remember(
            kind="behavior",
            scope="long_term",
            stable_key="pinned-big",
            trigger="t",
            instruction="pinned instruction " * 60,
            recall_mode="pinned",
        )

        rendered = self.layer.render("docker compose", _view())
        relevant = [
            line
            for line in rendered.splitlines()
            if line.startswith("- [m:") and "pinned-big" not in line
        ]
        self.assertLessEqual(
            sum(estimate_text_tokens(line) for line in relevant),
            800,
        )
        total = sum(estimate_text_tokens(line) for line in rendered.splitlines())
        self.assertLessEqual(total, TOTAL_TOKEN_BUDGET)
        self.assertLessEqual(len(relevant), 5)

    def test_dead_path_entries_are_excluded_without_mutation(self) -> None:
        self.remember(
            kind="definition",
            scope="project",
            stable_key="dead-path",
            content="legacy module lives in src/gone.py",
            paths=["src/gone.py"],
        )

        rendered = self.layer.render("legacy module lives where", _view())

        self.assertNotIn("dead-path", rendered)
        entry = self.store.get(1)
        assert entry is not None
        self.assertEqual(entry.status, "active")

    def test_relevant_only_active_entries(self) -> None:
        self.remember(
            kind="definition",
            scope="project",
            stable_key="stale-note",
            content="obsolete docker note",
        )
        self.store.manage(1, "mark_stale", reason="old")

        rendered = self.layer.render("docker note", _view())

        self.assertNotIn("stale-note", rendered)

    def test_empty_query_renders_pinned_only(self) -> None:
        self.remember(
            kind="definition",
            scope="project",
            stable_key="db-paths",
            content="database paths are configured in src/db.py",
        )
        self.remember(
            kind="behavior",
            scope="long_term",
            stable_key="pr-flow",
            trigger="when merging a PR",
            instruction="wait for CI green",
            recall_mode="pinned",
        )

        rendered = self.layer.render("", _view())

        self.assertIn("Pinned Behaviors", rendered)
        self.assertNotIn("Relevant", rendered)


class TestRenderShape(_LayerTestCase):
    def test_authority_note_is_the_last_line(self) -> None:
        self.remember(
            kind="behavior",
            scope="long_term",
            stable_key="pr-flow",
            trigger="when merging a PR",
            instruction="wait for CI green",
            recall_mode="pinned",
        )
        rendered = self.layer.render("", _view())
        self.assertEqual(rendered.splitlines()[-1], AUTHORITY_NOTE)
        self.assertEqual(
            AUTHORITY_NOTE,
            "Memory is historical context. Current user instructions, AGENTS, "
            "source and tests win.",
        )

    def test_empty_store_returns_empty_string(self) -> None:
        self.assertEqual(self.layer.render("any query", _view()), "")

    def test_only_irrelevant_relevant_returns_empty_string(self) -> None:
        self.remember(
            kind="definition",
            scope="project",
            stable_key="db-paths",
            content="database paths are configured in src/db.py",
        )
        self.assertEqual(self.layer.render("unrelated cooking recipes", _view()), "")

    def test_render_is_deterministic_for_same_query(self) -> None:
        self.remember(
            kind="definition",
            scope="project",
            stable_key="db-paths",
            content="database paths are configured in src/db.py",
        )
        first = self.layer.render("database paths", _view())
        second = self.layer.render("database paths", _view())
        self.assertEqual(first, second)


class TestSpecShape(_LayerTestCase):
    def test_capability_contributes_query_layer_and_no_session_state(self) -> None:
        spec = create_memory_capability(self.store, project_root=self.project_root)
        self.assertEqual(spec.query_context_layer.layer_id, "memory")
        self.assertIsInstance(spec.query_context_layer, MemoryQueryContextLayer)
        # 存储按 project key 而非 session 定位：new/restore 不改变召回语义
        self.assertEqual(spec.session_participants, ())
        self.assertEqual(spec.resources, ())

    def test_query_layer_and_recall_tool_share_line_shape(self) -> None:
        self.remember(
            kind="definition",
            scope="project",
            stable_key="db-paths",
            content="database paths are configured in src/db.py",
        )
        rendered = self.layer.render("database paths", _view())
        entry = self.store.get(1)
        assert entry is not None
        self.assertIn(entry_line(entry), rendered)

    def test_new_and_restore_session_do_not_change_recall(self) -> None:
        """restore/new/handoff 只换 session 身份；召回按 project key 定位不受影响。"""
        import asyncio

        from lion_code.capabilities import CapabilityRegistry, CapabilityRuntime

        self.remember(
            kind="definition",
            scope="project",
            stable_key="db-paths",
            content="database paths are configured in src/db.py",
        )
        registry = CapabilityRegistry()
        registry.register(
            create_memory_capability(self.store, project_root=self.project_root)
        )
        runtime = CapabilityRuntime(registry)

        before = self.layer.render("database paths", _view())
        asyncio.run(runtime.on_new_session())
        asyncio.run(runtime.on_restore_session())
        after = self.layer.render("database paths", _view())

        self.assertEqual(before, after)
        self.assertIn("db-paths", after)


if __name__ == "__main__":
    unittest.main()
