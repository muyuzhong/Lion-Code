from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lion_code.core.messages import UserMessage
from lion_code.core.session import (
    LabelEntry,
    MessageEntry,
    SessionInfoEntry,
    SessionJsonlError,
)
from lion_code.session_runtime import SessionRepository


class TestSessionRepository(unittest.IsolatedAsyncioTestCase):
    async def test_load_list_exists_and_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repository = SessionRepository(Path(tmp))
            self.assertFalse(repository.exists("s1"))
            self.assertIsNone(await repository.load("s1"))

            storage = repository.storage_for("s1")
            info = SessionInfoEntry(id="info", created_at=10, cwd="/work")
            await storage.append(info)
            await storage.append(
                MessageEntry(
                    id="message",
                    parent_id=info.id,
                    message=UserMessage(content="hello"),
                )
            )

            self.assertTrue(repository.exists("s1"))
            state = await repository.load("s1")
            self.assertEqual(state.messages[0].text, "hello")
            self.assertEqual((await repository.list_sessions())[0]["cwd"], "/work")
            self.assertIsNone((await repository.list_sessions())[0]["label"])
            self.assertTrue(await repository.rename("s1", "需求文档"))
            self.assertEqual((await repository.list_sessions())[0]["label"], "需求文档")
            entries = await storage.read_all()
            self.assertIsInstance(entries[-1], LabelEntry)
            self.assertEqual(entries[-1].parent_id, "message")
            self.assertEqual(await repository.latest_session_id(), "s1")

    async def test_incomplete_tail_is_ignored_and_removed_before_append(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repository = SessionRepository(Path(tmp))
            storage = repository.storage_for("s1")
            first = SessionInfoEntry(id="one")
            second = MessageEntry(
                id="two",
                parent_id=first.id,
                message=UserMessage(content="complete"),
            )
            await storage.append(first)
            await storage.append(second)
            with storage.path.open("ab") as file:
                file.write(b'{"type":"message","content":"\xe4\xb8')

            self.assertEqual([entry.id for entry in await storage.read_all()], ["one", "two"])

            third = MessageEntry(
                id="three",
                parent_id=second.id,
                message=UserMessage(content="after crash"),
            )
            await storage.append(third)
            self.assertEqual(
                [entry.id for entry in await storage.read_all()],
                ["one", "two", "three"],
            )

    async def test_invalid_complete_line_reports_session_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repository = SessionRepository(Path(tmp))
            path = repository.storage_for("s1").path
            path.write_text('{"type":"broken"}\n', encoding="utf-8")

            with self.assertRaisesRegex(SessionJsonlError, "line 1"):
                await repository.load("s1")

    async def test_session_id_cannot_escape_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repository = SessionRepository(Path(tmp))
            with self.assertRaises(ValueError):
                repository.storage_for("../outside")


if __name__ == "__main__":
    unittest.main()
