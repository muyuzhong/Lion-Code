"""Opik 后置导出结果解析与 Linux 宿主 publisher。"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .models import (
    AdapterStatus,
    DeepEvalAnalysis,
    DeepEvalTrajectory,
    FailureSource,
    OpikExportResult,
    OpikExportStatus,
    OpikFeedback,
    OpikSpan,
    OpikTracePayload,
    TaskResult,
    TaskVerdict,
    utc_now,
)
from .trace import redact_text

OPIK_EXPORT_SCHEMA_VERSION = "opik-export-result/v1"
OPIK_SDK_VERSION = "2.2.42"
OPIK_DEFAULT_PROJECT = "lion-agent-e2e"


class OpikExportError(ValueError):
    """Opik 导出 fixture 不符合固定 schema 或敏感边界。"""


class OpikExportSchemaError(OpikExportError):
    """检测到 schema 漂移或未知字段。"""


class OpikDependencyError(OpikExportError):
    """Opik optional dependency 不可用。"""


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


def build_opik_trace_payload(
    *,
    run_id: str,
    task_id: str,
    attempt: int,
    commit_sha: str,
    profile_fingerprint: str,
    trajectory: DeepEvalTrajectory,
    analysis: DeepEvalAnalysis | None = None,
    task_result: TaskResult | None = None,
    patch_sha256: str | None = None,
    execution_status: str = "completed",
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> OpikTracePayload:
    """从同一份脱敏 trajectory 构造宿主侧 Opik span/feedback payload。"""

    if trajectory.task_id != task_id:
        raise ValueError("Opik trajectory task_id does not match the requested task")
    if analysis is not None and (
        analysis.task_id != task_id
        or analysis.trajectory_digest != trajectory.trace_digest
    ):
        raise ValueError("Opik analysis does not match the requested trajectory")
    if task_result is not None and task_result.task_id != task_id:
        raise ValueError("Opik task_result task_id does not match the requested task")
    spans = _build_opik_spans(
        trajectory,
        execution_status=execution_status,
        started_at=started_at or (task_result.started_at if task_result else None),
        finished_at=finished_at or (task_result.finished_at if task_result else None),
    )
    metadata = {
        "run_id": _required_safe_name(run_id, max_length=128),
        "task_id": _required_safe_name(task_id, max_length=160),
        "attempt": str(attempt),
        "commit_sha": _required_safe_name(commit_sha, max_length=128),
        "profile_fingerprint": profile_fingerprint,
        "trajectory_digest": trajectory.trace_digest,
        "execution_status": _required_safe_name(execution_status, max_length=64),
    }
    if patch_sha256 is not None:
        metadata["patch_sha256"] = patch_sha256
    if task_result is not None:
        metadata["harness_verdict"] = task_result.verdict.value
        metadata["harness_validity"] = task_result.validity.value
        metadata["harness_official"] = str(task_result.official).lower()
    if analysis is not None:
        metadata["deepeval_status"] = analysis.status.value
    feedback = list(_analysis_feedback(analysis))
    if task_result is not None:
        feedback.append(_harness_feedback(task_result))
    return OpikTracePayload(
        run_id=run_id,
        task_id=task_id,
        attempt=attempt,
        commit_sha=commit_sha,
        profile_fingerprint=profile_fingerprint,
        spans=spans,
        feedback=tuple(feedback),
        metadata=metadata,
    )


def publish_opik_trace(
    payload: OpikTracePayload,
    *,
    client: Any | None = None,
    environ: Mapping[str, str] | None = None,
    project_name: str | None = None,
    workspace: str | None = None,
    timeout_seconds: float = 30.0,
    export_attempt: int = 1,
) -> OpikExportResult:
    """在宿主侧发布已完成的 payload，并显式 flush；不重新运行 Agent。"""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if export_attempt < 1:
        raise ValueError("export_attempt must be positive")
    environment = os.environ if environ is None else environ
    safe_workspace = _safe_name(workspace or environment.get("OPIK_WORKSPACE"))
    safe_project = (
        _safe_name(
            project_name
            or environment.get("OPIK_PROJECT_NAME")
            or OPIK_DEFAULT_PROJECT
        )
        or OPIK_DEFAULT_PROJECT
    )
    opik_client = client
    if opik_client is None:
        api_key = environment.get("OPIK_API_KEY")
        if not api_key or not safe_workspace:
            return _opik_failure(
                payload,
                status=OpikExportStatus.UNAVAILABLE,
                reason="Opik credentials are unavailable on the host",
                workspace=safe_workspace,
                project=safe_project,
                attempts=export_attempt,
            )
        try:
            opik_client = _build_opik_client(
                api_key=api_key,
                workspace=safe_workspace,
                project_name=safe_project,
            )
        except OpikDependencyError:
            return _opik_failure(
                payload,
                status=OpikExportStatus.UNAVAILABLE,
                reason="Opik SDK is unavailable",
                workspace=safe_workspace,
                project=safe_project,
                attempts=export_attempt,
            )
        except Exception:
            return _opik_failure(
                payload,
                status=OpikExportStatus.FAILED,
                reason="Opik client cannot be initialized",
                workspace=safe_workspace,
                project=safe_project,
                attempts=export_attempt,
            )
    try:
        trace = opik_client.trace(
            name=_trace_name(payload),
            start_time=payload.spans[0].started_at,
            end_time=payload.spans[0].finished_at,
            input={"trajectory_digest": payload.spans[0].input_digest},
            output={"status": payload.spans[0].status},
            metadata=payload.metadata,
            tags=["lion", "agent-e2e"],
            project_name=safe_project,
        )
        trace_id = _object_id(trace)
        if not trace_id:
            raise OpikExportError("Opik client did not return a trace_id")
        actual_span_ids: dict[str, str] = {}
        for span in payload.spans:
            parent_id = actual_span_ids.get(span.parent_id) if span.parent_id else None
            created = _publish_span(
                trace,
                span,
                parent_id=parent_id,
            )
            actual_span_ids[span.span_id] = _object_id(created) or span.span_id
        for feedback in payload.feedback:
            if feedback.value is None:
                continue
            _publish_feedback(trace, feedback)
        flush_result = opik_client.flush(timeout=timeout_seconds)
        if flush_result is False:
            return _opik_failure(
                payload,
                status=OpikExportStatus.TIMEOUT,
                reason="Opik flush did not complete",
                workspace=safe_workspace,
                project=safe_project,
                attempts=export_attempt,
            )
        return OpikExportResult(
            run_id=payload.run_id,
            task_id=payload.task_id,
            status=OpikExportStatus.EXPORTED,
            payload_digest=payload.fingerprint(),
            trace_id=str(trace_id),
            workspace=safe_workspace,
            project=safe_project,
            attempts=export_attempt,
        )
    except TimeoutError:
        return _opik_failure(
            payload,
            status=OpikExportStatus.TIMEOUT,
            reason="Opik export timed out",
            workspace=safe_workspace,
            project=safe_project,
            attempts=export_attempt,
        )
    except ImportError:
        return _opik_failure(
            payload,
            status=OpikExportStatus.UNAVAILABLE,
            reason="Opik SDK is unavailable",
            workspace=safe_workspace,
            project=safe_project,
            attempts=export_attempt,
        )
    except Exception:
        return _opik_failure(
            payload,
            status=OpikExportStatus.FAILED,
            reason="Opik export failed",
            workspace=safe_workspace,
            project=safe_project,
            attempts=export_attempt,
        )


def retry_opik_export(
    payload: OpikTracePayload,
    *,
    previous_result: OpikExportResult | None = None,
    client: Any | None = None,
    environ: Mapping[str, str] | None = None,
    project_name: str | None = None,
    workspace: str | None = None,
    timeout_seconds: float = 30.0,
) -> OpikExportResult:
    """重用已脱敏 payload 重试发布，不重新运行 Agent 或 DeepEval。"""

    if previous_result is not None and (
        previous_result.run_id != payload.run_id
        or previous_result.task_id != payload.task_id
    ):
        raise ValueError("Opik retry result does not match the payload")
    export_attempt = previous_result.attempts + 1 if previous_result else 2
    return publish_opik_trace(
        payload,
        client=client,
        environ=environ,
        project_name=project_name,
        workspace=workspace,
        timeout_seconds=timeout_seconds,
        export_attempt=export_attempt,
    )


def _build_opik_spans(
    trajectory: DeepEvalTrajectory,
    *,
    execution_status: str,
    started_at: datetime | None,
    finished_at: datetime | None,
) -> tuple[OpikSpan, ...]:
    event_starts = [
        event.started_at
        for event in trajectory.events
        if event.started_at is not None
    ]
    event_finishes = [
        event.finished_at
        for event in trajectory.events
        if event.finished_at is not None
    ]
    root_start = min(
        [item for item in [started_at, *event_starts] if item is not None],
        default=utc_now(),
    )
    root_finish = max(
        [item for item in [finished_at, *event_finishes] if item is not None],
        default=root_start,
    )
    if root_finish < root_start:
        raise ValueError("Opik trace finished_at must not precede started_at")
    root_id = f"agent:{trajectory.trace_id}"[:160]
    spans = [
        OpikSpan(
            span_id=root_id,
            span_type="agent",
            name="lion-agent-run",
            started_at=root_start,
            finished_at=root_finish,
            status=_safe_status(execution_status),
            output_digest=trajectory.trace_digest,
            summary="redacted Lion agent trajectory",
        )
    ]
    for event in trajectory.events:
        event_start = event.started_at or event.finished_at or root_start
        event_finish = event.finished_at or event_start
        if event_finish < event_start:
            raise ValueError("Opik span finished_at must not precede started_at")
        name = _safe_name(event.tool_name or event.event_type) or "trajectory-event"
        spans.append(
            OpikSpan(
                span_id=f"event:{event.sequence}"[:160],
                parent_id=root_id,
                span_type=_span_type(event.event_type, event.tool_name),
                name=name,
                started_at=event_start,
                finished_at=event_finish,
                status=_event_status(event.event_type),
                input_digest=event.argument_digest,
                output_digest=event.payload_digest,
                summary=_event_summary(event.event_type, event.tool_name),
            )
        )
    return tuple(spans)


def _analysis_feedback(analysis: DeepEvalAnalysis | None) -> tuple[OpikFeedback, ...]:
    if analysis is None:
        return ()
    return tuple(
        OpikFeedback(
            name=metric.name,
            value=metric.score if metric.status is AdapterStatus.COMPLETED else None,
            reason=_safe_feedback_reason(metric.reason),
        )
        for metric in analysis.metrics
    )


def _harness_feedback(task_result: TaskResult) -> OpikFeedback:
    value = None
    if task_result.verdict is TaskVerdict.PASSED:
        value = 1.0
    elif task_result.verdict is TaskVerdict.FAILED:
        value = 0.0
    return OpikFeedback(
        name="HarnessVerdict",
        value=value,
        reason=_safe_feedback_reason(
            "verdict="
            f"{task_result.verdict.value}; validity={task_result.validity.value}; "
            f"official={str(task_result.official).lower()}"
        ),
    )


def _build_opik_client(
    *,
    api_key: str,
    workspace: str,
    project_name: str,
) -> Any:
    try:
        from opik import Opik
    except ImportError as error:
        raise OpikDependencyError("Opik SDK is unavailable") from error
    return Opik(
        api_key=api_key,
        workspace=workspace,
        project_name=project_name,
        batching=True,
    )


def _publish_span(trace: Any, span: OpikSpan, *, parent_id: str | None) -> Any:
    trace_span = getattr(trace, "span", None)
    if not callable(trace_span):
        raise OpikExportError("Opik trace does not support child spans")
    return trace_span(
        parent_span_id=parent_id,
        name=span.name,
        type=_opik_span_type(span.span_type),
        start_time=span.started_at,
        end_time=span.finished_at,
        metadata={"status": span.status, "summary": span.summary},
        input={"digest": span.input_digest} if span.input_digest else {},
        output={"digest": span.output_digest} if span.output_digest else {},
        tags=["lion", "agent-e2e"],
    )


def _publish_feedback(trace: Any, feedback: OpikFeedback) -> None:
    log_feedback = getattr(trace, "log_feedback_score", None)
    if not callable(log_feedback):
        raise OpikExportError("Opik trace does not support feedback scores")
    log_feedback(
        name=feedback.name,
        value=feedback.value,
        reason=feedback.reason,
    )


def _object_id(value: Any) -> str | None:
    if isinstance(value, Mapping):
        candidate = value.get("id") or value.get("trace_id")
        return str(candidate) if candidate else None
    for item in (value, getattr(value, "data", None)):
        candidate = getattr(item, "id", None) or getattr(item, "trace_id", None)
        if candidate:
            return str(candidate)
    return None


def _opik_failure(
    payload: OpikTracePayload,
    *,
    status: OpikExportStatus,
    reason: str,
    workspace: str | None,
    project: str | None,
    attempts: int,
) -> OpikExportResult:
    return OpikExportResult(
        run_id=payload.run_id,
        task_id=payload.task_id,
        status=status,
        payload_digest=payload.fingerprint(),
        workspace=workspace,
        project=project,
        attempts=attempts,
        failure_source=_failure_source_for_status(status),
        reason=reason,
    )


def _trace_name(payload: OpikTracePayload) -> str:
    return _required_safe_name(
        f"lion:{payload.run_id}:{payload.task_id}",
        max_length=160,
    )


def _required_safe_name(value: str, *, max_length: int) -> str:
    safe = _safe_name(value)
    return (safe or "unknown")[:max_length]


def _safe_status(value: str) -> str:
    return _required_safe_name(value, max_length=64)


def _event_status(event_type: str) -> str:
    normalized = event_type.casefold()
    if any(word in normalized for word in ("error", "fail", "timeout", "cancel")):
        return "failed"
    return "completed"


def _span_type(event_type: str, tool_name: str | None) -> Literal["agent", "llm", "tool", "error"]:
    normalized = event_type.casefold()
    if tool_name:
        return "tool"
    if any(word in normalized for word in ("llm", "model", "assistant", "provider")):
        return "llm"
    if any(word in normalized for word in ("error", "fail", "timeout", "cancel")):
        return "error"
    return "agent"


def _opik_span_type(span_type: Literal["agent", "llm", "tool", "error"]) -> str:
    return "general" if span_type in {"agent", "error"} else span_type


def _event_summary(event_type: str, tool_name: str | None) -> str:
    label = _required_safe_name(event_type, max_length=120)
    if tool_name:
        label = f"{label}; tool={_required_safe_name(tool_name, max_length=120)}"
    return label[:320]


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


def _safe_feedback_reason(value: str | None) -> str | None:
    if value is None:
        return None
    safe, _ = redact_text(value, max_length=320)
    return safe.strip() or None


__all__: Sequence[str] = (
    "OPIK_DEFAULT_PROJECT",
    "OPIK_EXPORT_SCHEMA_VERSION",
    "OPIK_SDK_VERSION",
    "OpikDependencyError",
    "OpikExportError",
    "OpikExportFixture",
    "OpikExportSchemaError",
    "build_opik_trace_payload",
    "map_opik_status",
    "opik_export_result_json",
    "parse_opik_export_result",
    "publish_opik_trace",
    "retry_opik_export",
)
