"""项目级短期工作状态的轻量、原子持久化。"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lion_code.core.messages import (
    AgentMessage,
    AssistantMessage,
    ToolCall,
    ToolResultMessage,
)
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


@dataclass(frozen=True, slots=True)
class SessionMemoryEvidence:
    """从 canonical 工具消息确定性提取的短期状态事实。"""

    relevant_files: tuple[str, ...] = ()
    verification: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "relevantFiles": list(self.relevant_files),
            "verification": list(self.verification),
            "blockers": list(self.blockers),
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


def format_session_memory(memory: SessionMemory) -> str:
    """把完整短期状态格式化为固定 Provider Overlay。"""

    rows = ["# Project Session Memory", f"Project root: {memory.project_root}"]
    _append_text(rows, "Current goal", memory.current_goal)
    _append_text(rows, "Active task", memory.active_task)
    _append_items(rows, "Completed", memory.completed)
    _append_items(rows, "Pending", memory.pending)
    _append_items(rows, "Decisions", memory.decisions)
    _append_items(rows, "Blockers", memory.blockers)
    _append_items(rows, "Relevant files", memory.relevant_files)
    _append_items(rows, "Verification", memory.verification)
    _append_text(rows, "Previous handoff", memory.previous_handoff)
    _append_text(rows, "Next step", memory.next_step)
    return "\n".join(rows)


def extract_tool_evidence(
    messages: Sequence[AgentMessage],
) -> SessionMemoryEvidence:
    """从该轮 canonical 工具调用/结果配对中提取不可由模型伪造的事实。"""

    calls: dict[str, ToolCall] = {}
    relevant_files: list[str] = []
    verification: list[str] = []
    blockers: list[str] = []
    for message in messages:
        if isinstance(message, AssistantMessage):
            calls.update({call.id: call for call in message.tool_calls})
            continue
        if not isinstance(message, ToolResultMessage):
            continue
        call = calls.get(message.tool_call_id)
        arguments = call.arguments if call is not None else {}
        path = arguments.get("file_path")
        failed = _tool_failed(message)
        if (
            not failed
            and message.tool_name in {"read_file", "write_file", "edit_file"}
            and isinstance(path, str)
        ):
            relevant_files.append(path)
        command = arguments.get("command")
        if (
            message.tool_name == "run_shell"
            and isinstance(command, str)
            and _is_verification_command(command)
        ):
            status = "failed" if failed else "passed"
            verification.append(f"{_brief(command, 180)}: {status}")
        if failed:
            blockers.append(
                f"{message.tool_name} failed: {_brief(message.text, 240)}"
            )
    return SessionMemoryEvidence(
        relevant_files=_merge_items((), relevant_files),
        verification=_merge_items((), verification),
        blockers=_merge_items((), blockers),
    )


def apply_tool_evidence(
    memory: SessionMemory,
    evidence: SessionMemoryEvidence,
) -> SessionMemory:
    """合并确定性工具事实；语义层无法删除这些字段。"""

    return replace(
        memory,
        relevant_files=_merge_items(memory.relevant_files, evidence.relevant_files),
        verification=_merge_items(memory.verification, evidence.verification),
        blockers=_merge_items(memory.blockers, evidence.blockers),
    )


def apply_semantic_patch(
    memory: SessionMemory,
    patch: Mapping[str, object],
) -> SessionMemory:
    """仅接受任务语义字段，避免模型覆盖工具事实。"""

    updates: dict[str, object] = {}
    for source, target in {
        "currentGoal": "current_goal",
        "activeTask": "active_task",
        "previousHandoff": "previous_handoff",
        "nextStep": "next_step",
    }.items():
        value = patch.get(source)
        if source in patch and (value is None or isinstance(value, str)):
            updates[target] = value

    for source, target in {
        "completed": "completed",
        "decisions": "decisions",
        "blockers": "blockers",
    }.items():
        value = patch.get(source)
        if _is_text_list(value):
            updates[target] = _merge_items(getattr(memory, target), value)

    pending = patch.get("pending")
    if _is_text_list(pending):
        updates["pending"] = _merge_items((), pending)
    return replace(memory, **updates)


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


def _append_text(rows: list[str], label: str, value: str | None) -> None:
    if value:
        rows.extend((f"## {label}", value))


def _append_items(rows: list[str], label: str, values: tuple[str, ...]) -> None:
    if values:
        rows.extend((f"## {label}", *(f"- {value}" for value in values)))


def _merge_items(
    existing: Sequence[str],
    additions: Sequence[str],
    *,
    limit: int = 50,
) -> tuple[str, ...]:
    merged: list[str] = []
    for value in (*existing, *additions):
        value = value.strip()
        if value and value not in merged:
            merged.append(value)
        if len(merged) == limit:
            break
    return tuple(merged)


def _is_text_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _tool_failed(result: ToolResultMessage) -> bool:
    text = result.text.lower()
    return result.is_error or any(marker in text for marker in (
        "command failed (exit code",
        "command timed out",
        "error:",
        "error reading",
        "error writing",
        "error editing",
    ))


def _is_verification_command(command: str) -> bool:
    normalized = command.lower()
    markers = (
        "pytest",
        "unittest",
        "ruff",
        "mypy",
        "pyright",
        "compileall",
        "typecheck",
        "type-check",
        "lint",
        "tsc",
        "go test",
        "cargo test",
        "mvn test",
        "gradle test",
        "npm test",
        "pnpm test",
        "yarn test",
        "npm run build",
        "pnpm run build",
        "yarn build",
    )
    return any(marker in normalized for marker in markers)


def _brief(text: str, limit: int) -> str:
    normalized = " ".join(text.split())
    return normalized[:limit] + ("…" if len(normalized) > limit else "")
