"""受控 Core 事件轨迹：脱敏、摘要化与循环候选指纹。"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pydantic import BaseModel, Field

from .evidence import ProcessEvidence, ProcessEvidenceProjector
from .models import TraceSummary, VersionedModel, utc_now

if TYPE_CHECKING:
    from .analysis_trace import AnalysisTrace, AnalysisTraceProjector

REDACTED = "[REDACTED]"
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "cookie",
    "password",
    "secret",
    "session",
    "token",
)
_PATH_KEYS = {"cwd", "directory", "file", "path", "workspace"}
_SECRET_VALUE = re.compile(
    r"(?ix)(?:\bauthorization\s*[:=]\s*bearer\s+[^\s,;]+"
    r"|\b(?:api[_-]?key|authorization|password|secret|token)\b"
    r"\s*[:=]\s*[^\s,;]+|\bbearer\s+[^\s,;]+|\bsk-[a-z0-9_-]{8,})"
)


class TraceEvent(VersionedModel):
    """持久化前已脱敏的单条事件摘要。"""

    sequence: int = Field(ge=1)
    event_type: str = Field(min_length=1, max_length=160)
    summary: str = Field(max_length=320)
    payload_digest: str = Field(min_length=64, max_length=64)
    tool_name: str | None = Field(default=None, max_length=160)
    argument_digest: str | None = Field(default=None, min_length=64, max_length=64)
    workspace_fingerprint: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    started_at: datetime | None = None
    finished_at: datetime | None = None


class LoopCandidate(VersionedModel):
    """仅标记可复核的死循环候选，不替代人工失败归因。"""

    loop_fingerprint: str = Field(min_length=64, max_length=64)
    tool_name: str = Field(min_length=1, max_length=160)
    repetitions: int = Field(ge=3)


class TraceRecorder:
    """订阅 typed Core event 的同步监听器，绝不把原始内容当日志保存。"""

    def __init__(
        self,
        *,
        trace_id: str | None = None,
        max_preview: int = 240,
        projector: ProcessEvidenceProjector | None = None,
        analysis_projector: AnalysisTraceProjector | None = None,
        analysis_workspace: str | Path | None = None,
    ) -> None:
        self.trace_id = trace_id or uuid4().hex
        self._max_preview = max_preview
        self._events: list[TraceEvent] = []
        self._evidence: list[ProcessEvidence] = []
        self._projector = projector or ProcessEvidenceProjector()
        if analysis_projector is None:
            from .analysis_trace import (
                AnalysisTraceProjector as _AnalysisTraceProjector,
            )

            analysis_projector = _AnalysisTraceProjector(workspace=analysis_workspace)
        self._analysis_projector = analysis_projector
        self._redaction_count = 0
        self._loop_candidates: list[LoopCandidate] = []
        self._last_loop_fingerprint: str | None = None
        self._last_loop_tool: str | None = None
        self._loop_repetitions = 0

    @property
    def events(self) -> tuple[TraceEvent, ...]:
        """返回不可变事件快照，供 worker 写入其受控结果。"""

        return tuple(self._events)

    @property
    def evidence(self) -> tuple[ProcessEvidence, ...]:
        """返回过程证据快照（与被投影 TraceEvent 的 sequence 对齐）。"""

        return tuple(self._evidence)

    @property
    def loop_candidates(self) -> tuple[LoopCandidate, ...]:
        """返回达到阈值的循环候选。"""

        return tuple(self._loop_candidates)

    def record(self, event: object) -> None:
        """记录一个 Core event；该签名可直接传给 Agent 的 ``subscribe``。"""

        raw_payload = _event_payload(event)
        event_type = (
            str(raw_payload.get("event_type") or raw_payload.get("type"))
            if isinstance(raw_payload, Mapping)
            and (raw_payload.get("event_type") or raw_payload.get("type"))
            else event.__class__.__name__
        )
        safe_payload, redaction_count = sanitize_payload(raw_payload)
        self._redaction_count += redaction_count
        tool_name = _find_text(safe_payload, "tool_name", "name", "toolName")
        arguments = _find_mapping(safe_payload, "arguments", "args", "input")
        workspace_value = _find_text(
            safe_payload,
            "workspace_fingerprint",
            "workspace",
            "cwd",
            "path",
        )
        argument_digest = _digest(arguments) if arguments is not None else None
        workspace_fingerprint = (
            _normalize_workspace_fingerprint(workspace_value)
            if workspace_value is not None
            else None
        )
        if tool_name is not None and arguments is not None:
            self._observe_loop(
                tool_name=tool_name,
                argument_digest=argument_digest,
                workspace_fingerprint=workspace_fingerprint,
            )
        started_at, finished_at = _event_timestamps(raw_payload)
        sequence = len(self._events) + 1
        self._events.append(
            TraceEvent(
                sequence=sequence,
                event_type=event_type,
                summary=_event_summary(event_type, safe_payload, self._max_preview),
                payload_digest=_digest(safe_payload),
                tool_name=tool_name,
                argument_digest=argument_digest,
                workspace_fingerprint=workspace_fingerprint,
                started_at=started_at,
                finished_at=finished_at,
            )
        )
        evidence = self._projector.project(event, sequence=sequence)
        if evidence is not None:
            self._evidence.append(evidence)
        self._analysis_projector.project(event, sequence=sequence)

    def record_tool_call(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, Any],
        workspace_fingerprint: str | None = None,
    ) -> str:
        """记录合成工具调用并返回稳定循环指纹，便于离线规则测试。"""

        safe_arguments, redaction_count = sanitize_payload(dict(arguments))
        self._redaction_count += redaction_count
        argument_digest = _digest(safe_arguments)
        normalized_workspace = _normalize_workspace_fingerprint(workspace_fingerprint)
        fingerprint = self._observe_loop(
            tool_name=tool_name,
            argument_digest=argument_digest,
            workspace_fingerprint=normalized_workspace,
        )
        recorded_at = utc_now()
        sequence = len(self._events) + 1
        self._events.append(
            TraceEvent(
                sequence=sequence,
                event_type="ToolCall",
                summary=_event_summary(
                    "ToolCall",
                    {"tool_name": tool_name, "arguments": safe_arguments},
                    self._max_preview,
                ),
                payload_digest=_digest(
                    {"tool_name": tool_name, "arguments": safe_arguments}
                ),
                tool_name=tool_name,
                argument_digest=argument_digest,
                workspace_fingerprint=normalized_workspace,
                started_at=recorded_at,
                finished_at=recorded_at,
            )
        )
        synthetic = {
            "type": "tool_execution_end",
            "tool_name": tool_name,
            "args": dict(arguments),
            "is_error": False,
        }
        self._analysis_projector.project(
            {
                "type": "tool_execution_start",
                "tool_name": tool_name,
                "tool_call_id": f"synthetic-{sequence}",
                "args": dict(arguments),
            },
            sequence=sequence,
        )
        evidence = self._projector.project(synthetic, sequence=sequence)
        if evidence is not None:
            self._evidence.append(evidence)
        return fingerprint

    def summary(self) -> TraceSummary:
        """生成可安全放进 ``TaskResult`` 的 trace 摘要。"""

        event_types = tuple(sorted({event.event_type for event in self._events}))
        digest = _digest([event.model_dump(mode="json") for event in self._events])
        return TraceSummary(
            trace_id=self.trace_id,
            event_count=len(self._events),
            event_types=event_types,
            redaction_count=self._redaction_count,
            loop_fingerprints=tuple(
                candidate.loop_fingerprint for candidate in self._loop_candidates
            ),
            trace_digest=digest,
        )

    def build_analysis_trace(self, *, task_id: str) -> AnalysisTrace:
        """生成供 DeepEval 使用的安全语义轨迹。"""

        return self._analysis_projector.build(
            task_id=task_id,
            trace_id=self.trace_id,
        )

    def write_analysis_trace(self, path: str | Path, *, task_id: str) -> Path:
        """写入已校验的 Analysis Trace。"""

        return self.build_analysis_trace(task_id=task_id).write_json(path)

    def write_json(self, path: str | Path) -> None:
        """写入已脱敏事件；调用方负责把位置保持在 host 控制的结果目录。"""

        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "agent-e2e/v1",
            "trace_id": self.trace_id,
            "events": [event.model_dump(mode="json") for event in self._events],
            "evidence": [
                evidence.model_dump(mode="json") for evidence in self._evidence
            ],
            "loop_candidates": [
                candidate.model_dump(mode="json") for candidate in self._loop_candidates
            ],
        }
        destination.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _observe_loop(
        self,
        *,
        tool_name: str,
        argument_digest: str | None,
        workspace_fingerprint: str | None,
    ) -> str:
        fingerprint = loop_fingerprint(
            tool_name=tool_name,
            argument_digest=argument_digest or _digest({}),
            workspace_fingerprint=workspace_fingerprint,
        )
        if fingerprint == self._last_loop_fingerprint:
            self._loop_repetitions += 1
        else:
            self._last_loop_fingerprint = fingerprint
            self._last_loop_tool = tool_name
            self._loop_repetitions = 1
        if self._loop_repetitions >= 3 and not any(
            candidate.loop_fingerprint == fingerprint
            for candidate in self._loop_candidates
        ):
            self._loop_candidates.append(
                LoopCandidate(
                    loop_fingerprint=fingerprint,
                    tool_name=self._last_loop_tool or tool_name,
                    repetitions=self._loop_repetitions,
                )
            )
        return fingerprint


def loop_fingerprint(
    *,
    tool_name: str,
    argument_digest: str,
    workspace_fingerprint: str | None,
) -> str:
    """对同一工具/参数/无进展工作区生成稳定候选指纹。"""

    return _digest(
        {
            "tool_name": tool_name,
            "argument_digest": argument_digest,
            "workspace_fingerprint": workspace_fingerprint,
        }
    )


def redact_text(value: str, *, max_length: int = 240) -> tuple[str, int]:
    """删除常见内联凭证，并将正文限制为不超过 ``max_length`` 的受控预览。"""

    redacted, replacements = _SECRET_VALUE.subn(REDACTED, value)
    if len(redacted) > max_length:
        redacted = f"{redacted[: max_length - 1]}…"
    return redacted, replacements


def sanitize_payload(value: Any, *, key: str | None = None) -> tuple[Any, int]:
    """递归脱敏事件内容，同时让摘要保留足够的结构供复核。"""

    normalized_key = key.casefold() if key else ""
    if normalized_key and any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
        return REDACTED, 1
    if normalized_key in _PATH_KEYS:
        return _path_fingerprint(str(value)), 1
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        redactions = 0
        for item_key, item_value in value.items():
            safe_value, count = sanitize_payload(item_value, key=str(item_key))
            result[str(item_key)] = safe_value
            redactions += count
        return result, redactions
    if isinstance(value, (list, tuple, set, frozenset)):
        items: list[Any] = []
        redactions = 0
        for item in value:
            safe_value, count = sanitize_payload(item)
            items.append(safe_value)
            redactions += count
        return items, redactions
    if isinstance(value, Path):
        return _path_fingerprint(str(value)), 1
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}:{hashlib.sha256(value).hexdigest()}>", 0
    if isinstance(value, Enum):
        return value.value, 0
    if isinstance(value, str):
        return redact_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value, 0
    # 不使用 repr(value)：第三方 event 的 repr 可能泄露 prompt、session 或凭证。
    return f"<{value.__class__.__name__}>", 0


def _event_payload(event: object) -> Mapping[str, Any]:
    if isinstance(event, Mapping):
        return dict(event)
    if isinstance(event, BaseModel):
        payload = event.model_dump(mode="json")
        return payload if isinstance(payload, Mapping) else {}
    if is_dataclass(event):
        payload = asdict(event)
        return payload if isinstance(payload, Mapping) else {}
    values = getattr(event, "__dict__", None)
    return dict(values) if isinstance(values, Mapping) else {}


def _event_summary(event_type: str, payload: Any, max_preview: int) -> str:
    if not isinstance(payload, Mapping) or not payload:
        return event_type
    selected: list[str] = []
    # 不把任意 message/error 正文带进 trace：第三方事件可能把用户提示、工具输出
    # 或 provider 原文放在这些字段中。摘要只保留受控的流程元数据。
    for key in ("tool_name", "name", "toolName", "reason", "stop_reason"):
        value = payload.get(key)
        if isinstance(value, (str, int, float, bool)):
            preview, _ = redact_text(str(value), max_length=max_preview)
            selected.append(f"{key}={preview}")
    if not selected:
        selected.append(f"fields={','.join(sorted(str(key) for key in payload)[:6])}")
    return f"{event_type}: {'; '.join(selected)}"[:320]


def _event_timestamps(payload: Mapping[str, Any]) -> tuple[datetime, datetime]:
    """从事件提取受控时间元数据；无消息时间戳时以记录时刻为准。

    Core 事件自身没有时间字段：消息类事件（Message*/Turn*）带
    ``message.timestamp``（Unix 毫秒），工具执行类事件不携带 message。
    两者都是事件刚发生的时刻，统一作为 started/finished（事件级精度）。
    """

    timestamp_ms = _message_timestamp_ms(payload.get("message"))
    if timestamp_ms is None:
        recorded_at = utc_now()
        return recorded_at, recorded_at
    instant = _utc_from_ms(timestamp_ms)
    return instant, instant


def _message_timestamp_ms(value: Any) -> int | None:
    if not isinstance(value, Mapping):
        return None
    timestamp = value.get("timestamp")
    if isinstance(timestamp, int) and timestamp >= 0:
        return timestamp
    return None


def _utc_from_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=UTC)


def _find_text(payload: Any, *keys: str) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value != REDACTED:
            return value
    return None


def _find_mapping(payload: Any, *keys: str) -> Mapping[str, Any] | None:
    if not isinstance(payload, Mapping):
        return None
    for key in keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def _normalize_workspace_fingerprint(value: str | None) -> str | None:
    if value is None:
        return None
    if re.fullmatch(r"[0-9a-f]{64}", value):
        return value
    return _path_fingerprint(value)


def _path_fingerprint(value: str) -> str:
    return f"<path:{hashlib.sha256(value.encode('utf-8')).hexdigest()}>"


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
