"""应用层 Session 仓库：定位、重放和枚举 JSONL 会话。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lion_code.core.session import JsonlSessionStorage, SessionJsonlError, SessionState

SESSION_DIR = Path.home() / ".lion-code" / "sessions"


class SessionRepository:
    """管理本机 JSONL Session；Entry 写入仍由 SessionRecorder 负责。"""

    def __init__(self, session_dir: Path | None = None) -> None:
        self.session_dir = session_dir or SESSION_DIR

    def storage_for(self, session_id: str) -> JsonlSessionStorage:
        return JsonlSessionStorage(self.session_dir / f"{_safe_session_id(session_id)}.jsonl")

    def exists(self, session_id: str) -> bool:
        return self.storage_for(session_id).path.exists()

    def delete(self, session_id: str) -> None:
        """删除 Session 文件；仅用于清理本进程刚创建、未生效的失败 Session。

        append-only 契约约束的是已生效会话的历史 Entry；这里删除的是
        handoff 回滚中从未激活过的全新文件，不触碰任何已生效历史。
        """
        self.storage_for(session_id).path.unlink(missing_ok=True)

    async def load(self, session_id: str) -> SessionState | None:
        entries = await self.storage_for(session_id).read_all()
        if not entries:
            return None
        return SessionState.from_entries(entries)

    async def list_sessions(self) -> list[dict[str, Any]]:
        if not self.session_dir.exists():
            return []

        sessions: list[dict[str, Any]] = []
        for path in self.session_dir.glob("*.jsonl"):
            try:
                state = await self.load(path.stem)
            except (OSError, SessionJsonlError, ValueError):
                continue
            if state is None:
                continue
            created_at = (
                state.session_info.created_at
                if state.session_info is not None
                else path.stat().st_mtime
            )
            sessions.append(
                {
                    "id": path.stem,
                    "model": state.model,
                    "cwd": state.session_info.cwd if state.session_info else None,
                    "startTime": _format_timestamp(created_at),
                    "messageCount": len(state.messages),
                    "format": "jsonl",
                }
            )
        sessions.sort(key=lambda item: item["startTime"], reverse=True)
        return sessions

    async def latest_session_id(self) -> str | None:
        sessions = await self.list_sessions()
        return str(sessions[0]["id"]) if sessions else None


def _safe_session_id(session_id: str) -> str:
    if not session_id or Path(session_id).name != session_id or session_id in {".", ".."}:
        raise ValueError("Invalid session id")
    return session_id


def _format_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
