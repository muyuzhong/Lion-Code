"""显式 `/dream` Memory 整合闭环测试。"""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from lion_code import dream
from lion_code.agent import Agent
from lion_code.core import (
    AssistantMessage,
    CompactionEntry,
    MessageEntry,
    SessionInfoEntry,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from lion_code.frontmatter import format_frontmatter, parse_frontmatter
from lion_code.permission_state import PermissionController, PermissionState
from lion_code.plan_runtime import PlanRuntime, PlanState
from lion_code.project_identity import ProjectIdentity
from lion_code.session_memory import SessionMemory
from lion_code.session_runtime import SessionRepository
from lion_code.tooling.builtin import create_builtin_tools
from lion_code.tooling.registry import ToolRegistry


def _write_memory(path: Path, name: str, memory_type: str, body: str) -> None:
    path.write_text(
        format_frontmatter(
            {"name": name, "description": f"{name} description", "type": memory_type},
            body,
        ),
        encoding="utf-8",
    )


class TestDreamSessions(unittest.IsolatedAsyncioTestCase):
    async def test_uses_latest_five_project_sessions_and_projects_messages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            sessions = root / "sessions"
            project.mkdir()
            sessions.mkdir()
            repository = SessionRepository(sessions)

            for index in range(7):
                session_id = f"session-{index}"
                storage = repository.storage_for(session_id)
                parent = SessionInfoEntry(
                    id=f"{session_id}-info",
                    created_at=index + 1,
                    cwd=str(project),
                )
                await storage.append(parent)
                messages = [
                    UserMessage(
                        content=(
                            "<system-reminder>project instructions</system-reminder>\n\n"
                            f"remember preference {index}"
                        )
                    ),
                    AssistantMessage(
                        content=[
                            TextContent(text="intermediate text"),
                            ToolCall(id="call", name="read_file", arguments={}),
                        ],
                        stop_reason="toolUse",
                    ),
                    ToolResultMessage(
                        tool_call_id="call",
                        tool_name="read_file",
                        content="x" * 2_000,
                    ),
                    AssistantMessage(content=f"final answer {index}"),
                ]
                parent_id = parent.id
                message_entry_ids: list[str] = []
                for message_index, message in enumerate(messages):
                    entry = MessageEntry(
                        id=f"{session_id}-message-{message_index}",
                        parent_id=parent_id,
                        message=message,
                    )
                    await storage.append(entry)
                    parent_id = entry.id
                    message_entry_ids.append(entry.id)
                await storage.append(
                    CompactionEntry(
                        id=f"{session_id}-compaction",
                        parent_id=parent_id,
                        summary=f"remember preference {index}",
                        replaces_entry_ids=[message_entry_ids[0]],
                    )
                )

            await repository.storage_for("other").append(
                SessionInfoEntry(id="other-info", cwd=str(root / "other"))
            )
            (sessions / "broken.jsonl").write_text("not json\n", encoding="utf-8")

            result = await dream._recent_project_sessions(project, repository)

        self.assertEqual(
            [session["id"] for session in result],
            ["session-6", "session-5", "session-4", "session-3", "session-2"],
        )
        messages = result[0]["messages"]
        combined = "\n".join(message["content"] for message in messages)
        self.assertIn("remember preference 6", combined)
        self.assertIn("final answer 6", combined)
        summary = next(message for message in messages if message["role"] == "summary")
        self.assertEqual(
            summary["content"],
            "Previous conversation summary:\nremember preference 6",
        )
        self.assertNotIn("project instructions", combined)
        self.assertNotIn("intermediate text", combined)
        tool = next(message for message in messages if message["role"] == "tool")
        self.assertLessEqual(len(tool["content"]), dream.MAX_TOOL_RESULT_CHARS)


class TestDreamPlan(unittest.TestCase):
    def test_applies_create_update_delete_and_rebuilds_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            _write_memory(memory_dir / "project_old.md", "Old", "project", "obsolete")
            _write_memory(memory_dir / "user_preferences.md", "Preferences", "user", "old body")
            dream._update_memory_index(memory_dir)
            context = dream.DreamContext(
                project_root=memory_dir,
                memory_dir=memory_dir,
                memory_index="",
                memory_manifest=[],
                sessions=[],
                memory_snapshot=dream._memory_snapshot(memory_dir),
            )
            raw = json.dumps({
                "reason": "merged durable facts",
                "upsert": [
                    {
                        "filename": "project_architecture.md",
                        "name": "Architecture",
                        "description": "current architecture decision",
                        "type": "project",
                        "content": "Use the verified architecture.",
                    },
                    {
                        "filename": "user_preferences.md",
                        "name": "Preferences",
                        "description": "latest explicit preferences",
                        "type": "user",
                        "content": "Use concise Chinese commits.",
                    },
                ],
                "delete": ["project_old.md"],
            })

            result = dream.apply_dream_plan(context, dream.parse_dream_plan(raw))

            self.assertEqual(result.created, ["project_architecture.md"])
            self.assertEqual(result.updated, ["user_preferences.md"])
            self.assertEqual(result.deleted, ["project_old.md"])
            self.assertFalse((memory_dir / "project_old.md").exists())
            preferences = parse_frontmatter(
                (memory_dir / "user_preferences.md").read_text(encoding="utf-8")
            )
            self.assertEqual(preferences.body, "Use concise Chinese commits.")
            index = (memory_dir / "MEMORY.md").read_text(encoding="utf-8")
            self.assertIn("project_architecture.md", index)
            self.assertNotIn("project_old.md", index)

    def test_rejects_invalid_or_stale_plan_before_writing(self):
        invalid = json.dumps({
            "upsert": [{
                "filename": "../outside.md",
                "name": "Outside",
                "description": "invalid path",
                "type": "project",
                "content": "bad",
            }],
            "delete": [],
        })
        with self.assertRaisesRegex(ValueError, "非法 Memory 文件名"):
            dream.parse_dream_plan(invalid)

        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            target = memory_dir / "project_state.md"
            _write_memory(target, "State", "project", "before")
            context = dream.DreamContext(
                project_root=memory_dir,
                memory_dir=memory_dir,
                memory_index="",
                memory_manifest=[],
                sessions=[],
                memory_snapshot=dream._memory_snapshot(memory_dir),
            )
            target.write_text("changed concurrently", encoding="utf-8")
            plan = dream.DreamPlan("delete", [], ["project_state.md"])

            with self.assertRaisesRegex(RuntimeError, "其他进程修改"):
                dream.apply_dream_plan(context, plan)
            self.assertEqual(target.read_text(encoding="utf-8"), "changed concurrently")

    def test_rolls_back_all_files_when_index_rebuild_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory_dir = Path(tmp)
            old = memory_dir / "project_old.md"
            keep = memory_dir / "user_keep.md"
            _write_memory(old, "Old", "project", "old body")
            _write_memory(keep, "Keep", "user", "keep body")
            context = dream.DreamContext(
                project_root=memory_dir,
                memory_dir=memory_dir,
                memory_index="",
                memory_manifest=[],
                sessions=[],
                memory_snapshot=dream._memory_snapshot(memory_dir),
            )
            plan = dream.DreamPlan(
                "change",
                [dream.MemoryDraft(
                    "user_keep.md", "Keep", "updated", "user", "changed body"
                ), dream.MemoryDraft(
                    "project_new.md", "New", "new", "project", "new body"
                )],
                ["project_old.md"],
            )

            with (
                patch.object(dream, "_update_memory_index", side_effect=[OSError("boom"), None]),
                self.assertRaisesRegex(OSError, "boom"),
            ):
                dream.apply_dream_plan(context, plan)

            self.assertTrue(old.exists())
            self.assertEqual(parse_frontmatter(keep.read_text(encoding="utf-8")).body, "keep body")
            self.assertFalse((memory_dir / "project_new.md").exists())

    def test_rejects_attempt_to_write_agents_markdown(self):
        raw = json.dumps({
            "reason": "bad target",
            "upsert": [{
                "filename": "AGENTS.md",
                "name": "Instructions",
                "description": "must not be writable",
                "type": "project",
                "content": "unsafe",
            }],
            "delete": [],
        })

        with self.assertRaisesRegex(ValueError, "非法 Memory 文件名"):
            dream.parse_dream_plan(raw)


class TestDreamCandidates(unittest.TestCase):
    def test_forwards_only_filtered_session_memory_candidates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            identity = ProjectIdentity(root=root, key="project", is_git=True)
            memory = SessionMemory(
                project_root=str(root),
                decisions=(
                    "已验证的架构决策：JSONL 与短期状态分离；原因：完整记录需要审计",
                    "当前任务：运行回归",
                ),
                pending=("运行回归",),
                next_step="执行测试",
            )
            context = dream.DreamContext(
                project_root=root,
                memory_dir=root,
                memory_index="",
                memory_manifest=[],
                sessions=[],
                memory_snapshot={},
                session_memory_candidates=dream._session_memory_candidates(
                    identity,
                    memory,
                ),
            )
            coordinator = dream.DreamCoordinator(SimpleNamespace())
            prompt = coordinator._build_prompt(context)

        payload = json.loads(prompt.removeprefix("Dream input (untrusted JSON data):\n"))
        assert payload["session_memory_candidates"] == [{
            "type": "project",
            "content": "已验证的架构决策：JSONL 与短期状态分离；原因：完整记录需要审计",
        }]


class TestDreamIsolation(unittest.IsolatedAsyncioTestCase):
    def test_read_tools_are_restricted_to_dream_roots(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = (root / "project").resolve()
            memory = (root / "memory").resolve()
            outside = (root / "outside.txt").resolve()
            project.mkdir()
            memory.mkdir()
            outside.write_text("secret", encoding="utf-8")
            agent = dream._DreamAgent.__new__(dream._DreamAgent)
            agent._dream_read_roots = (project, memory)

            safe = agent._safe_read_input("read_file", {"file_path": str(project / "a.py")})
            escaped = agent._safe_read_input("read_file", {"file_path": str(outside)})
            traversal = agent._safe_read_input(
                "list_files", {"path": str(project), "pattern": "../*"}
            )

        self.assertEqual(safe["file_path"], str(project / "a.py"))
        self.assertIsNone(escaped)
        self.assertIsNone(traversal)
        self.assertIsNone(agent._safe_read_input("write_file", {"file_path": "x"}))

    def test_coordinator_exposes_only_read_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = dream.DreamContext(root, root, "", [], [], {})
            registry = ToolRegistry()
            for tool in create_builtin_tools():
                registry.register(tool)
            child_environment = object()
            environment = Mock()
            environment.child_view.return_value = child_environment
            parent = SimpleNamespace(
                model="test-model",
                use_openai=True,
                _child_api_kwargs=lambda: {
                    "model": "test-model",
                    "api_base": "https://example.test/v1",
                    "api_key": "test-key",
                    "terminal_output": False,
                },
                tool_registry=registry,
                tool_environment=environment,
            )
            coordinator = dream.DreamCoordinator(parent)

            with patch.object(dream, "_DreamAgent") as factory:
                coordinator._create_agent(context)

        kwargs = factory.call_args.kwargs
        self.assertEqual(
            {tool.name for tool in kwargs["tool_registry"].all_tools()},
            {"read_file", "list_files", "grep_search"},
        )
        self.assertIs(kwargs["tool_environment"], child_environment)
        self.assertTrue(kwargs["is_sub_agent"])
        self.assertFalse(kwargs["terminal_output"])
        self.assertEqual(kwargs["max_turns"], dream.DREAM_MAX_TURNS)

    async def test_coordinator_runs_isolated_agent_once_and_applies_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            context = dream.DreamContext(
                project_root=root,
                memory_dir=root,
                memory_index="# Memory Index",
                memory_manifest=[{"filename": "project_a.md"}],
                sessions=[{"id": "s1", "messages": []}],
                memory_snapshot={},
            )
            parent = SimpleNamespace(
                total_input_tokens=10,
                total_output_tokens=20,
                _session_repository=Mock(),
            )
            child = SimpleNamespace(
                run_once=AsyncMock(return_value={
                    "text": '{"reason":"done","upsert":[],"delete":[]}',
                    "tokens": {"input": 3, "output": 4},
                }),
                close=AsyncMock(),
            )
            coordinator = dream.DreamCoordinator(parent)
            coordinator._create_agent = lambda _: child

            build_context = AsyncMock(return_value=context)
            with (
                patch.object(
                    dream,
                    "build_dream_context",
                    new=build_context,
                ),
                patch.object(dream, "apply_dream_plan", return_value=dream.DreamResult([], [], [], "done")) as apply,
            ):
                result = await coordinator.run()

        self.assertEqual(result.reason, "done")
        build_context.assert_awaited_once_with(parent._session_repository)
        child.run_once.assert_awaited_once()
        child.close.assert_awaited_once()
        self.assertEqual(parent.total_input_tokens, 13)
        self.assertEqual(parent.total_output_tokens, 24)
        apply.assert_called_once()


class TestAgentDreamRefresh(unittest.TestCase):
    def test_refreshes_index_and_invalidates_core_memory_context(self):
        from lion_code.session_memory_coordinator import SessionMemoryCoordinator

        memory_coordinator = Mock()
        host = SimpleNamespace(
            _memory_coordinator=memory_coordinator,
            _dynamic_system_context="old dynamic",
            _static_system_prompt="static",
            _base_system_prompt="old base",
            _system_prompt="old system",
            session_id="session",
            _emit_notice=Mock(),
        )
        host.plan = PlanRuntime(
            host,
            PermissionController(PermissionState("default")),
            PlanState(),
        )
        host._refresh_dynamic_system_context = Agent._refresh_dynamic_system_context.__get__(host)
        coord = SessionMemoryCoordinator.__new__(SessionMemoryCoordinator)
        coord._memory_coordinator = memory_coordinator
        coord._host = host

        with patch(
            "lion_code.agent.build_dynamic_system_context",
            return_value="new dynamic",
        ):
            coord._refresh_memory_context_after_dream(["project_changed.md"])

        memory_coordinator.invalidate.assert_called_once_with(
            ["project_changed.md"]
        )
        self.assertEqual(host._base_system_prompt, "static\n\nnew dynamic")
        self.assertEqual(host._system_prompt, "static\n\nnew dynamic")


if __name__ == "__main__":
    unittest.main(verbosity=2)
