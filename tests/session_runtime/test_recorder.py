from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.fakes import FakeProvider

from lion_code.core.events import MessageEndEvent, MessageUpdateEvent
from lion_code.core.harness import AgentHarness, AgentHarnessConfig
from lion_code.core.messages import (
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from lion_code.core.provider_events import AssistantDoneEvent, TextDeltaEvent
from lion_code.core.session import JsonlSessionStorage, SessionInfoEntry, SessionState
from lion_code.session_runtime import SessionRecorder


class TestSessionRecorder(unittest.IsolatedAsyncioTestCase):
    async def test_message_end_events_are_appended_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = JsonlSessionStorage(Path(tmp) / "s1.jsonl")
            recorder = SessionRecorder(
                session_id="s1",
                model="fake-model",
                thinking_level="disabled",
                cwd=Path(tmp),
                storage=storage,
            )
            messages = [
                UserMessage(content="hello"),
                AssistantMessage(
                    model="fake-model",
                    content=[ToolCall(id="c1", name="echo", arguments={})],
                    stop_reason="toolUse",
                ),
                ToolResultMessage(
                    tool_call_id="c1",
                    tool_name="echo",
                    content=[TextContent(text="ok")],
                ),
                AssistantMessage(model="fake-model", content="done"),
            ]

            await recorder.handle(
                MessageUpdateEvent(
                    message=messages[1],
                    assistant_message_event=TextDeltaEvent(
                        partial=messages[1],
                        content_index=0,
                        delta="ignored",
                    ),
                )
            )
            for message in messages:
                await recorder.handle(MessageEndEvent(message=message))

            entries = await storage.read_all()
            self.assertEqual(
                [entry.type for entry in entries],
                [
                    "session_info",
                    "model_change",
                    "thinking_level_change",
                    "message",
                    "message",
                    "message",
                    "message",
                ],
            )
            state = SessionState.from_entries(entries)
            self.assertEqual([message.role for message in state.messages], [
                "user", "assistant", "toolResult", "assistant",
            ])
            self.assertEqual(state.model, "fake-model")
            self.assertEqual(state.thinking_level, "disabled")

    async def test_existing_session_continues_from_last_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = JsonlSessionStorage(Path(tmp) / "s1.jsonl")
            first = SessionRecorder(
                session_id="s1",
                model="m1",
                thinking_level="disabled",
                cwd=Path(tmp),
                storage=storage,
            )
            await first.record_message(UserMessage(content="first"))

            second = SessionRecorder(
                session_id="s1",
                model="ignored",
                thinking_level=None,
                cwd=Path(tmp),
                storage=storage,
            )
            await second.record_message(AssistantMessage(model="m1", content="second"))

            entries = await storage.read_all()
            self.assertEqual(entries[-1].parent_id, entries[-2].id)
            self.assertEqual(len(SessionState.from_entries(entries).messages), 2)

    async def test_label_keeps_recorder_parent_chain_and_skips_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = JsonlSessionStorage(Path(tmp) / "s1.jsonl")
            recorder = SessionRecorder(
                session_id="s1",
                model="m1",
                thinking_level="disabled",
                cwd=Path(tmp),
                storage=storage,
            )

            first = await recorder.record_label("需求文档")
            duplicate = await recorder.record_label("需求文档")
            message = await recorder.record_message(UserMessage(content="continue"))

            self.assertIsNotNone(first)
            self.assertIsNone(duplicate)
            self.assertEqual(message.parent_id, first.id if first else None)
            self.assertEqual(SessionState.from_entries(await storage.read_all()).label, "需求文档")

    async def test_initialization_repairs_metadata_interrupted_after_info(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = JsonlSessionStorage(Path(tmp) / "s1.jsonl")
            await storage.append(SessionInfoEntry(id="info", cwd=tmp))
            recorder = SessionRecorder(
                session_id="s1",
                model="m1",
                thinking_level="disabled",
                cwd=Path(tmp),
                storage=storage,
            )

            await recorder.initialize()

            entries = await storage.read_all()
            self.assertEqual(
                [entry.type for entry in entries],
                ["session_info", "model_change", "thinking_level_change"],
            )
            self.assertEqual(entries[1].parent_id, "info")

    async def test_initialize_does_not_create_file_for_new_session(self) -> None:
        """全新会话初始化不落盘；首条消息才创建 JSONL（R3 回归）。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s-new.jsonl"
            storage = JsonlSessionStorage(path)
            recorder = SessionRecorder(
                session_id="s-new",
                model="m1",
                thinking_level="disabled",
                cwd=Path(tmp),
                storage=storage,
            )

            await recorder.initialize()
            self.assertFalse(path.exists())

            # 配置变更在未落盘会话上不产生仅配置的空文件。
            await recorder.record_model_change("m2")
            await recorder.record_thinking_level_change("high")
            self.assertFalse(path.exists())

            # 首条消息触发初始三行 + 消息本身落盘。
            await recorder.record_message(UserMessage(content="hello"))
            self.assertTrue(path.exists())
            state = SessionState.from_entries(await storage.read_all())
            self.assertEqual(state.model, "m2")
            self.assertEqual(state.thinking_level, "high")
            self.assertEqual(len(state.messages), 1)

    async def test_ensure_on_disk_persists_empty_session(self) -> None:
        """显式落盘路径（legacy 迁移）即使零消息也创建文件（R3 例外）。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s-migrated.jsonl"
            storage = JsonlSessionStorage(path)
            recorder = SessionRecorder(
                session_id="s-migrated",
                model="m1",
                thinking_level="disabled",
                cwd=Path(tmp),
                storage=storage,
            )

            await recorder.ensure_on_disk()
            self.assertTrue(path.exists())
            state = SessionState.from_entries(await storage.read_all())
            self.assertEqual(state.model, "m1")
            self.assertEqual(len(state.messages), 0)

    async def test_compaction_changes_replay_but_retains_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = JsonlSessionStorage(Path(tmp) / "s1.jsonl")
            recorder = SessionRecorder(
                session_id="s1",
                model="m1",
                thinking_level="disabled",
                cwd=Path(tmp),
                storage=storage,
            )
            await recorder.record_message(UserMessage(content="old one"))
            await recorder.record_message(AssistantMessage(model="m1", content="old two"))
            recent = await recorder.record_message(UserMessage(content="recent"))
            ids = list(await recorder.context_entry_ids())
            await recorder.record_compaction(
                summary="condensed",
                replaces_entry_ids=ids[:2],
            )

            entries = await storage.read_all()
            state = SessionState.from_entries(entries)
            self.assertEqual(
                [message.text for message in state.messages],
                ["Previous conversation summary:\ncondensed", "recent"],
            )
            self.assertEqual(state.context_entry_ids[-1], recent.id)
            self.assertEqual(len(state.entries), 7)

    async def test_interrupted_tool_repair_is_persisted_through_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = JsonlSessionStorage(Path(tmp) / "s1.jsonl")
            recorder = SessionRecorder(
                session_id="s1",
                model="m1",
                thinking_level="disabled",
                cwd=Path(tmp),
                storage=storage,
            )
            pending = AssistantMessage(
                model="m1",
                content=[ToolCall(id="pending", name="echo", arguments={})],
                stop_reason="toolUse",
            )
            await recorder.record_message(pending)
            provider = FakeProvider([
                AssistantDoneEvent(
                    reason="stop",
                    message=AssistantMessage(model="m1", content="continued"),
                )
            ])
            harness = AgentHarness(
                AgentHarnessConfig(provider=provider, model="m1", system="test"),
                messages=[pending],
            )
            harness.subscribe(recorder.handle)

            async for _ in harness.prompt("continue"):
                pass

            state = SessionState.from_entries(await storage.read_all())
            self.assertEqual(
                [message.role for message in state.messages],
                ["assistant", "toolResult", "user", "assistant"],
            )
            self.assertTrue(state.messages[1].is_error)
            self.assertEqual(state.messages[1].tool_call_id, "pending")


if __name__ == "__main__":
    unittest.main()
