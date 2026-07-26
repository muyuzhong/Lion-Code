from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lion_code.core.events import MessageEndEvent, MessageUpdateEvent
from lion_code.core.messages import (
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from lion_code.core.provider_events import TextDeltaEvent
from lion_code.core.session import JsonlSessionStorage, SessionState
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


if __name__ == "__main__":
    unittest.main()
