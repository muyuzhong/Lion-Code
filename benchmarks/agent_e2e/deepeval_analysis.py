"""DeepEval fixture 解析与脱敏 trajectory 投影。

阶段一只处理固定版本的结果契约。这里没有 DeepEval SDK import、装饰器或 judge
调用；真实分析器在后续阶段通过窄边界接入，Windows/CI 仍可离线验证 schema 和
敏感信息边界。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .models import (
    AdapterStatus,
    DeepEvalAnalysis,
    DeepEvalAnalysisStatus,
    DeepEvalMetricResult,
    DeepEvalTrajectory,
    DeepEvalTrajectoryEvent,
    FailureSource,
)
from .trace import TraceEvent, redact_text

DEEPEVAL_RESULT_SCHEMA_VERSION = "deepeval-result/v1"
MAX_TRAJECTORY_EVENTS = 256
_EMPTY_DIGEST = hashlib.sha256(b"").hexdigest()


class DeepEvalResultError(ValueError):
    """DeepEval fixture 不满足固定 schema 或安全边界。"""


class DeepEvalSchemaError(DeepEvalResultError):
    """检测到版本漂移、未知字段或不完整的结果。"""


class DeepEvalMetricFixture(BaseModel):
    """固定 DeepEval metric 输出的 raw 输入模型。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=160)
    score: float | None = Field(default=None, ge=0, le=1)
    reason: str | None = Field(default=None, max_length=1000)
    status: str = "completed"


class DeepEvalResultFixture(BaseModel):
    """固定 DeepEval 分析 fixture；不会把完整 prompt/response 带入结果。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["deepeval-result/v1"]
    task_id: str = Field(min_length=1, max_length=160)
    status: str = Field(min_length=1, max_length=80)
    judge_model: str = Field(min_length=1, max_length=256)
    input_digest: str = Field(min_length=64, max_length=64)
    trajectory_digest: str = Field(min_length=64, max_length=64)
    metrics: tuple[DeepEvalMetricFixture, ...] = Field(default=(), max_length=64)
    error: str | None = Field(default=None, max_length=1000)


def parse_deepeval_analysis(
    payload: Mapping[str, Any] | str | Path,
    *,
    expected_task_id: str | None = None,
) -> DeepEvalAnalysis:
    """解析固定 DeepEval 结果，失败只属于分析器而非任务 verifier。"""

    raw = _load_payload(payload)
    _reject_sensitive_keys(raw)
    try:
        fixture = DeepEvalResultFixture.model_validate(raw)
    except ValidationError as error:
        raise DeepEvalSchemaError(str(error)) from error
    if expected_task_id is not None and fixture.task_id != expected_task_id:
        raise DeepEvalSchemaError(
            f"DeepEval task_id mismatch: expected {expected_task_id}, got {fixture.task_id}"
        )
    metric_names = [metric.name for metric in fixture.metrics]
    if len(set(metric_names)) != len(metric_names):
        raise DeepEvalSchemaError("DeepEval metric names must be unique")
    status, failure_source = map_deepeval_status(fixture.status)
    safe_reason = fixture.error
    if safe_reason is not None:
        safe_reason, _ = redact_text(safe_reason, max_length=320)
        safe_reason = safe_reason or None
    metrics: list[DeepEvalMetricResult] = []
    for metric in fixture.metrics:
        metric_status = _metric_status(metric.status)
        reason = metric.reason
        if reason is not None:
            reason, _ = redact_text(reason, max_length=320)
            reason = reason or None
        if metric_status is AdapterStatus.COMPLETED and metric.score is None:
            metric_status = AdapterStatus.INVALID
            reason = reason or "DeepEval metric is missing score"
        if metric_status is not AdapterStatus.COMPLETED and not reason:
            reason = f"DeepEval metric status: {metric.status}"
        metrics.append(
            DeepEvalMetricResult(
                name=metric.name,
                score=metric.score
                if metric_status is AdapterStatus.COMPLETED
                else None,
                reason=reason,
                model=fixture.judge_model,
                input_digest=fixture.input_digest,
                status=metric_status,
            )
        )
    if status is DeepEvalAnalysisStatus.COMPLETED and not metrics:
        status = DeepEvalAnalysisStatus.PARTIAL
        failure_source = FailureSource.DEEPEVAL
        safe_reason = safe_reason or "DeepEval completed result contains no metrics"
    if status is DeepEvalAnalysisStatus.COMPLETED and any(
        metric.status is not AdapterStatus.COMPLETED for metric in metrics
    ):
        status = DeepEvalAnalysisStatus.PARTIAL
        failure_source = FailureSource.DEEPEVAL
        safe_reason = safe_reason or "DeepEval result contains failed metrics"
    if status is not DeepEvalAnalysisStatus.COMPLETED and not safe_reason:
        safe_reason = f"DeepEval status: {fixture.status}"
    return DeepEvalAnalysis(
        task_id=fixture.task_id,
        status=status,
        judge_model=fixture.judge_model,
        input_digest=fixture.input_digest,
        trajectory_digest=fixture.trajectory_digest,
        metrics=tuple(metrics),
        failure_source=failure_source,
        reason=safe_reason,
    )


def map_deepeval_status(
    status: str,
) -> tuple[DeepEvalAnalysisStatus, FailureSource | None]:
    """归一化 DeepEval 状态，不与 Harbor/Harness 的任务状态混淆。"""

    normalized = status.casefold().replace("-", "_").replace(" ", "_")
    if normalized in {"completed", "success", "succeeded", "passed"}:
        return DeepEvalAnalysisStatus.COMPLETED, None
    if normalized in {"partial", "partial_failure", "incomplete"}:
        return DeepEvalAnalysisStatus.PARTIAL, FailureSource.DEEPEVAL
    if normalized in {"timeout", "timed_out"}:
        return DeepEvalAnalysisStatus.TIMEOUT, FailureSource.DEEPEVAL
    if normalized in {"unavailable", "blocked", "offline"}:
        return DeepEvalAnalysisStatus.UNAVAILABLE, FailureSource.DEEPEVAL
    return DeepEvalAnalysisStatus.FAILED, FailureSource.DEEPEVAL


def build_deepeval_trajectory(
    *,
    task_id: str,
    trace_id: str,
    trace_events: Sequence[TraceEvent],
    max_events: int = MAX_TRAJECTORY_EVENTS,
) -> DeepEvalTrajectory:
    """从 TraceEvent 仅投影 digest/工具元数据，不复制 summary 或正文。"""

    if max_events < 1 or max_events > MAX_TRAJECTORY_EVENTS:
        raise ValueError(f"max_events must be between 1 and {MAX_TRAJECTORY_EVENTS}")
    projected: list[DeepEvalTrajectoryEvent] = []
    for event in tuple(trace_events)[:max_events]:
        tool_name = None
        if event.tool_name is not None:
            tool_name, _ = redact_text(event.tool_name, max_length=160)
        projected.append(
            DeepEvalTrajectoryEvent(
                sequence=event.sequence,
                event_type=event.event_type,
                payload_digest=_digest_or_empty(event.payload_digest),
                tool_name=tool_name,
                argument_digest=_optional_digest(event.argument_digest),
                workspace_fingerprint=_optional_digest(event.workspace_fingerprint),
            )
        )
    digest = _digest_json([item.model_dump(mode="json") for item in projected])
    return DeepEvalTrajectory(
        task_id=task_id,
        trace_id=trace_id,
        trace_digest=digest,
        events=tuple(projected),
    )


def deepeval_analysis_json(analysis: DeepEvalAnalysis) -> str:
    """返回可持久化的受控 DeepEval 摘要。"""

    return analysis.canonical_json() + "\n"


def _metric_status(status: str) -> AdapterStatus:
    normalized = status.casefold().replace("-", "_").replace(" ", "_")
    if normalized in {"completed", "success", "succeeded", "passed"}:
        return AdapterStatus.COMPLETED
    if normalized in {"timeout", "timed_out"}:
        return AdapterStatus.TIMEOUT
    if normalized in {"unavailable", "blocked", "offline"}:
        return AdapterStatus.UNAVAILABLE
    return AdapterStatus.FAILED


def _load_payload(payload: Mapping[str, Any] | str | Path) -> Mapping[str, Any]:
    if isinstance(payload, Mapping):
        return dict(payload)
    try:
        loaded = json.loads(Path(payload).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DeepEvalResultError(
            f"Unable to read DeepEval result: {payload}"
        ) from error
    if not isinstance(loaded, Mapping):
        raise DeepEvalSchemaError("DeepEval result must be a JSON object")
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
                raise DeepEvalSchemaError("DeepEval result contains a sensitive field")
            _reject_sensitive_keys(nested)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for nested in value:
            _reject_sensitive_keys(nested)


def _optional_digest(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) == 64 and all(char in "0123456789abcdefABCDEF" for char in value):
        return value.lower()
    return _digest_json({"value": value})


def _digest_or_empty(value: str) -> str:
    return _optional_digest(value) or _EMPTY_DIGEST


def _digest_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__: Sequence[str] = (
    "DEEPEVAL_RESULT_SCHEMA_VERSION",
    "DeepEvalMetricFixture",
    "DeepEvalResultError",
    "DeepEvalResultFixture",
    "DeepEvalSchemaError",
    "build_deepeval_trajectory",
    "deepeval_analysis_json",
    "map_deepeval_status",
    "parse_deepeval_analysis",
)
