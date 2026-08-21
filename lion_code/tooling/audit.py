"""工具执行的独立、追加写入审计记录。"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .snapshot import is_sensitive_path
from .types import JSONValue, LionTool, ToolResult

AuditResult = Literal["success", "failed", "rolled_back", "blocked"]


@dataclass(frozen=True, slots=True)
class ExecutionEvent:
    """PR-S1 固定的执行事件 schema。"""

    event: Literal["execution"] = "execution"
    tool: str = ""
    command_or_args: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    snapshot_id: str | None = None
    result: AuditResult = "success"
    destination: str | None = None
    fingerprint_hit: bool | None = None
    authorization_source: str | None = None
    sanitizer_hits: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "event": self.event,
            "tool": self.tool,
            "command_or_args": self.command_or_args,
            "timestamp": self.timestamp,
            "snapshot_id": self.snapshot_id,
            "result": self.result,
            "destination": self.destination,
            "fingerprint_hit": self.fingerprint_hit,
            "authorization_source": self.authorization_source,
            "sanitizer_hits": self.sanitizer_hits,
            "notes": list(self.notes),
        }


class ExecutionAuditLog:
    """向专用文件追加 JSON 对象；不参与 Session JSONL。"""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser().resolve()
        self._lock = threading.RLock()

    def append(self, event: ExecutionEvent) -> None:
        """追加一条完整事件，并尽量限制目录与文件权限。"""
        if not isinstance(event, ExecutionEvent):
            raise TypeError("event must be an ExecutionEvent")
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                self.path.parent.chmod(0o700)
            except OSError:
                pass
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        event.to_dict(),
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                stream.write("\n")
            try:
                self.path.chmod(0o600)
            except OSError:
                pass

    def record_tool(
        self,
        tool: LionTool,
        arguments: Mapping[str, JSONValue],
        result: ToolResult,
    ) -> None:
        """从统一工具结果构造审计事件。"""
        snapshot_id = result.details.get("snapshot_id")
        sanitizer_hits = result.details.get("sanitizer_hits")
        self.append(
            ExecutionEvent(
                tool=tool.name,
                command_or_args=serialize_tool_arguments(tool, arguments),
                snapshot_id=snapshot_id if isinstance(snapshot_id, str) else None,
                sanitizer_hits=(
                    sanitizer_hits if isinstance(sanitizer_hits, int) else 0
                ),
                result="failed" if result.is_error else "success",
            )
        )


def serialize_tool_arguments(
    tool: LionTool,
    arguments: Mapping[str, JSONValue],
) -> str:
    """稳定序列化工具参数，并对敏感文件写入值做脱敏。"""
    if tool.capabilities.executes_process and isinstance(arguments.get("command"), str):
        return str(arguments["command"])
    values: dict[str, JSONValue] = dict(arguments)
    raw_path = values.get("file_path")
    if isinstance(raw_path, str) and is_sensitive_path(raw_path):
        for key in ("content", "old_string", "new_string"):
            if key in values:
                values[key] = "[REDACTED]"
    return json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
