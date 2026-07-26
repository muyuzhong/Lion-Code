"""Session storage protocols and JSONL implementation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from lion_code.core.session.entries import SessionEntry
from lion_code.core.session.jsonl import entries_from_json_lines, entry_to_json_line


class SessionStorage(Protocol):
    """Append-only session storage interface."""

    async def append(self, entry: SessionEntry) -> None:
        """Append one entry to storage."""
        ...

    async def read_all(self) -> list[SessionEntry]:
        """Read all entries in storage order."""
        ...


class JsonlSessionStorage:
    """Local append-only JSONL session storage."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    async def append(self, entry: SessionEntry) -> None:
        """Append one entry, creating parent directories if needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._discard_incomplete_tail()
        with self.path.open("a", encoding="utf-8") as file:
            file.write(entry_to_json_line(entry))
            file.flush()
            os.fsync(file.fileno())

    async def read_all(self) -> list[SessionEntry]:
        """Read all entries in file order. Missing files are empty sessions."""
        if not self.path.exists():
            return []
        # Split on newlines only: str.splitlines() would also split on characters
        # like U+2028 that appear unescaped inside JSON string values.
        content = self.path.read_text(encoding="utf-8")
        lines = content.split("\n")
        if content and not content.endswith("\n"):
            # append() 始终写入换行；无换行尾部只可能是进程中断留下的半条记录。
            lines.pop()
        return entries_from_json_lines(lines)

    def _discard_incomplete_tail(self) -> None:
        """追加前移除崩溃留下的半行，避免它污染后续完整记录。"""
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        with self.path.open("rb+") as file:
            file.seek(-1, os.SEEK_END)
            if file.read(1) == b"\n":
                return
            file.seek(0)
            content = file.read()
            last_newline = content.rfind(b"\n")
            file.truncate(last_newline + 1 if last_newline >= 0 else 0)
