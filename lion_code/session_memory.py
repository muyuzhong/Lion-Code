"""项目级短期工作状态的轻量、原子持久化。"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lion_code.project_identity import (
    ProjectIdentity,
    project_storage_dir,
    resolve_project_identity,
)

_SCHEMA_VERSION = 1
_FILENAME = "session-memory.json"


class SessionMemoryError(RuntimeError):
    """Session Memory 无法安全读取或写入时抛出。"""


@dataclass(frozen=True, slots=True)
class SessionMemory:
    """独立于 JSONL 会话的项目级短期工作状态。"""

    project_root: str
    current_goal: str | None = None
    active_task: str | None = None
    completed: tuple[str, ...] = ()
    pending: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    relevant_files: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    previous_handoff: str | None = None
    next_step: str | None = None
    updated_at: str | None = None

    @classmethod
    def empty(cls, project_root: Path) -> SessionMemory:
        """为尚未创建状态文件的项目提供内存中的空快照。"""

        return cls(project_root=str(project_root))

    @classmethod
    def from_dict(cls, data: object, *, expected_root: Path) -> SessionMemory:
        """验证并反序列化 schema v1，拒绝不安全的损坏内容。"""

        if not isinstance(data, dict):
            raise SessionMemoryError("Session Memory must contain a JSON object")
        if data.get("schemaVersion") != _SCHEMA_VERSION:
            raise SessionMemoryError(
                f"Unsupported Session Memory schema: {data.get('schemaVersion')!r}"
            )
        project_root = _required_text(data, "projectRoot")
        if Path(project_root).resolve() != expected_root:
            raise SessionMemoryError(
                "Session Memory projectRoot does not match the current project"
            )
        return cls(
            project_root=project_root,
            current_goal=_optional_text(data, "currentGoal"),
            active_task=_optional_text(data, "activeTask"),
            completed=_text_items(data, "completed"),
            pending=_text_items(data, "pending"),
            decisions=_text_items(data, "decisions"),
            blockers=_text_items(data, "blockers"),
            relevant_files=_text_items(data, "relevantFiles"),
            verification=_text_items(data, "verification"),
            previous_handoff=_optional_text(data, "previousHandoff"),
            next_step=_optional_text(data, "nextStep"),
            updated_at=_required_text(data, "updatedAt"),
        )

    def to_dict(self) -> dict[str, Any]:
        """生成稳定、可人工阅读的 schema v1 JSON。"""

        return {
            "schemaVersion": _SCHEMA_VERSION,
            "projectRoot": self.project_root,
            "currentGoal": self.current_goal,
            "activeTask": self.active_task,
            "completed": list(self.completed),
            "pending": list(self.pending),
            "decisions": list(self.decisions),
            "blockers": list(self.blockers),
            "relevantFiles": list(self.relevant_files),
            "verification": list(self.verification),
            "previousHandoff": self.previous_handoff,
            "nextStep": self.next_step,
            "updatedAt": self.updated_at,
        }


class SessionMemoryRepository:
    """以项目身份隔离的 Session Memory JSON 文件。"""

    def __init__(
        self,
        identity: ProjectIdentity | None = None,
        *,
        storage_dir: Path | None = None,
    ) -> None:
        self.identity = identity or resolve_project_identity()
        self.path = (storage_dir or project_storage_dir(self.identity)) / _FILENAME

    def load(self) -> SessionMemory:
        """读取状态；缺失文件仅表示尚无短期状态，损坏文件绝不覆盖。"""

        if not self.path.exists():
            return SessionMemory.empty(self.identity.root)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SessionMemoryError(
                f"Unable to read Session Memory at {self.path}: {error}"
            ) from error
        try:
            return SessionMemory.from_dict(data, expected_root=self.identity.root)
        except SessionMemoryError as error:
            raise SessionMemoryError(
                f"Invalid Session Memory at {self.path}: {error}"
            ) from error

    def save(self, memory: SessionMemory) -> SessionMemory:
        """原子替换状态文件，返回带更新时间的已保存快照。"""

        if Path(memory.project_root).resolve() != self.identity.root:
            raise SessionMemoryError(
                "Cannot save Session Memory for a different project"
            )
        saved = replace(memory, updated_at=_timestamp())
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(saved.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            raise SessionMemoryError(
                f"Unable to save Session Memory at {self.path}: {error}"
            ) from error
        return saved


def _required_text(data: dict[str, object], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise SessionMemoryError(f"{field} must be a non-empty string")
    return value


def _optional_text(data: dict[str, object], field: str) -> str | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SessionMemoryError(f"{field} must be a string or null")
    return value


def _text_items(data: dict[str, object], field: str) -> tuple[str, ...]:
    value = data.get(field, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SessionMemoryError(f"{field} must be a string list")
    return tuple(value)


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
