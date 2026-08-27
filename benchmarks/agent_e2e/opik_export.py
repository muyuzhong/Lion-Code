"""Opik 后置导出结果的离线 fixture 解析。

阶段一不连接 Opik Cloud，也不导入其 SDK。此模块只把宿主 publisher 的受控
fixture 归一化为 ``OpikExportResult``，供后续 Linux publisher 消费；API key、原始
span payload 和路径不属于该边界。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .models import FailureSource, OpikExportResult, OpikExportStatus
from .trace import redact_text

OPIK_EXPORT_SCHEMA_VERSION = "opik-export-result/v1"


class OpikExportError(ValueError):
    """Opik 导出 fixture 不符合固定 schema 或敏感边界。"""


class OpikExportSchemaError(OpikExportError):
    """检测到 schema 漂移或未知字段。"""


class OpikExportFixture(BaseModel):
    """publisher 输出的严格受控输入模型，不包含 API key。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["opik-export-result/v1"]
    run_id: str = Field(min_length=1, max_length=128)
    task_id: str = Field(min_length=1, max_length=160)
    status: str = Field(min_length=1, max_length=80)
    payload_digest: str = Field(min_length=64, max_length=64)
    trace_id: str | None = Field(default=None, max_length=160)
    workspace: str | None = Field(default=None, max_length=160)
    project: str | None = Field(default=None, max_length=160)
    attempts: int = Field(default=1, ge=0)
    error: str | None = Field(default=None, max_length=1000)


def parse_opik_export_result(
    payload: Mapping[str, Any] | str | Path,
    *,
    expected_run_id: str | None = None,
    expected_task_id: str | None = None,
) -> OpikExportResult:
    """解析 Opik export 状态，不把失败提升为任务失败。"""

    raw = _load_payload(payload)
    _reject_sensitive_keys(raw)
    try:
        fixture = OpikExportFixture.model_validate(raw)
    except ValidationError as error:
        raise OpikExportSchemaError(str(error)) from error
    if expected_run_id is not None and fixture.run_id != expected_run_id:
        raise OpikExportSchemaError("Opik run_id does not match the requested run")
    if expected_task_id is not None and fixture.task_id != expected_task_id:
        raise OpikExportSchemaError("Opik task_id does not match the requested task")
    status = map_opik_status(fixture.status)
    failure_source = _failure_source_for_status(status)
    reason = fixture.error
    if reason is not None:
        reason, _ = redact_text(reason, max_length=320)
        reason = reason or None
    if status is OpikExportStatus.EXPORTED and not fixture.trace_id:
        status = OpikExportStatus.FAILED
        failure_source = FailureSource.SCHEMA
        reason = reason or "Opik exported result is missing trace_id"
    if status is not OpikExportStatus.EXPORTED and not reason:
        reason = f"Opik export status: {fixture.status}"
    return OpikExportResult(
        run_id=fixture.run_id,
        task_id=fixture.task_id,
        status=status,
        payload_digest=fixture.payload_digest,
        trace_id=fixture.trace_id if status is OpikExportStatus.EXPORTED else None,
        workspace=_safe_name(fixture.workspace),
        project=_safe_name(fixture.project),
        attempts=fixture.attempts,
        failure_source=failure_source,
        reason=reason,
    )


def map_opik_status(status: str) -> OpikExportStatus:
    """归一化 publisher 状态，保留 timeout 与普通失败的区别。"""

    normalized = status.casefold().replace("-", "_").replace(" ", "_")
    if normalized in {"exported", "completed", "success", "succeeded"}:
        return OpikExportStatus.EXPORTED
    if normalized in {"timeout", "timed_out"}:
        return OpikExportStatus.TIMEOUT
    if normalized in {"unavailable", "blocked", "offline"}:
        return OpikExportStatus.UNAVAILABLE
    return OpikExportStatus.FAILED


def _failure_source_for_status(status: OpikExportStatus) -> FailureSource | None:
    if status is OpikExportStatus.EXPORTED:
        return None
    if status is OpikExportStatus.TIMEOUT:
        return FailureSource.TIMEOUT
    return FailureSource.OPIK


def opik_export_result_json(result: OpikExportResult) -> str:
    """返回不含凭证的稳定 JSON。"""

    return result.canonical_json() + "\n"


def _load_payload(payload: Mapping[str, Any] | str | Path) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return dict(payload)
    try:
        loaded = json.loads(Path(payload).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise OpikExportError(
            f"Unable to read Opik export result: {payload}"
        ) from error
    if not isinstance(loaded, Mapping):
        raise OpikExportSchemaError("Opik export result must be a JSON object")
    return dict(loaded)


def _reject_sensitive_keys(value: Any) -> None:
    forbidden = (
        "api_key",
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "password",
        "secret",
        "session",
        "token",
    )
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if any(part in str(key).casefold() for part in forbidden):
                raise OpikExportSchemaError(
                    "Opik export result contains a sensitive field"
                )
            _reject_sensitive_keys(nested)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for nested in value:
            _reject_sensitive_keys(nested)


def _safe_name(value: str | None) -> str | None:
    if value is None:
        return None
    safe, _ = redact_text(value, max_length=160)
    return safe


__all__: Sequence[str] = (
    "OPIK_EXPORT_SCHEMA_VERSION",
    "OpikExportError",
    "OpikExportFixture",
    "OpikExportSchemaError",
    "map_opik_status",
    "opik_export_result_json",
    "parse_opik_export_result",
)
