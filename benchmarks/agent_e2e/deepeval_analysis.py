"""DeepEval fixture 解析、脱敏 trajectory 投影与离线分析组合。"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .analysis_trace import AnalysisTrace
from .models import (
    AdapterStatus,
    DeepEvalAnalysis,
    DeepEvalAnalysisStatus,
    DeepEvalCase,
    DeepEvalMetricResult,
    DeepEvalScoreGate,
    DeepEvalTrajectory,
    DeepEvalTrajectoryEvent,
    FailureSource,
    TaskVerdict,
    VerifiedEvaluationReport,
)
from .trace import TraceEvent, redact_text

DEEPEVAL_RESULT_SCHEMA_VERSION = "deepeval-result/v1"
MAX_TRAJECTORY_EVENTS = 256
DEEPEVAL_METRIC_NAMES = (
    "ArgumentCorrectnessMetric",
    "ToolDecisionQuality",
)
# 投影前丢弃的高频流式快照：Core ``message_update`` 与 message_start/end
# 冗余（携带的是增量快照而非新事实），对脱敏 judge 无增量价值。
NOISE_EVENT_TYPES = frozenset({"message_update"})
# 两指标统一阈值（≥0.5 视为达阈值）：中点判定、简单可解释；运行侧策略
# 常量，演进只改此处与文档，不引入配置系统。score_gate 仅作观测，
# 不参与 task_result 判定与 CLI 退出码。
DEEPEVAL_METRIC_THRESHOLDS: Mapping[str, float] = {
    "ArgumentCorrectnessMetric": 0.5,
    "ToolDecisionQuality": 0.5,
}
_EMPTY_DIGEST = hashlib.sha256(b"").hexdigest()


class DeepEvalResultError(ValueError):
    """DeepEval fixture 不满足固定 schema 或安全边界。"""


class DeepEvalSchemaError(DeepEvalResultError):
    """检测到版本漂移、未知字段或不完整的结果。"""


class DeepEvalTelemetryError(DeepEvalResultError):
    """离线分析不允许携带 Confident AI 上报凭证。"""


class DeepEvalTimeoutError(TimeoutError):
    """DeepEval 单项分析超过宿主侧 deadline。"""


@dataclass(frozen=True, slots=True)
class DeepEvalMetricObservation:
    """窄 judge protocol 返回的单项、尚未持久化结果。"""

    name: str
    score: float | None
    reason: str | None = None
    model: str | None = None
    input_digest: str | None = None
    status: AdapterStatus = AdapterStatus.COMPLETED


@dataclass(frozen=True, slots=True)
class DeepEvalAnalysisCase:
    """供 DeepEval 使用的短生命周期语义 case，不作为结果模型持久化。"""

    task_id: str
    input_digest: str
    analysis_trace: AnalysisTrace
    expected_verdict: TaskVerdict | None = None
    input_preview: str | None = None
    outcome_preview: str | None = None


DeepEvalCaseLike = DeepEvalCase | DeepEvalAnalysisCase


class DeepEvalJudge(Protocol):
    """离线分析器使用的最小 judge 边界，便于 fake 测试。"""

    def evaluate_metric(
        self,
        *,
        metric_name: str,
        case: DeepEvalCaseLike,
    ) -> DeepEvalMetricObservation:
        """基于已有 case 计算一项固定 metric。"""


class DeepEvalMetricFixture(BaseModel):
    """固定 DeepEval metric 输出的 raw 输入模型。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=160)
    score: float | None = Field(default=None, ge=0, le=1)
    reason: str | None = Field(default=None, max_length=1000)
    status: str = "completed"
    samples: int = Field(default=1, ge=1)
    score_min: float | None = Field(default=None, ge=0, le=1)
    score_max: float | None = Field(default=None, ge=0, le=1)


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
        threshold = DEEPEVAL_METRIC_THRESHOLDS.get(metric.name)
        threshold_met = (
            None
            if threshold is None
            else metric_status is AdapterStatus.COMPLETED
            and metric.score is not None
            and float(metric.score) >= threshold
        )
        try:
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
                    threshold=threshold,
                    threshold_met=threshold_met,
                    samples=metric.samples,
                    score_min=metric.score_min,
                    score_max=metric.score_max,
                )
            )
        except ValidationError as error:
            raise DeepEvalSchemaError(str(error)) from error
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
        score_gate=_score_gate(tuple(metrics)),
        failure_source=failure_source,
        reason=safe_reason,
    )


def analyze_deepeval_case(
    case: DeepEvalCaseLike,
    *,
    judge_model: str,
    judge: DeepEvalJudge | None = None,
    timeout_seconds: float | None = 120.0,
    agent_model: str | None = None,
    judge_fingerprint: str | None = None,
    judge_samples: int = 3,
) -> DeepEvalAnalysis:
    """对冻结语义轨迹做两项离线分析，绝不修改正式 task verdict。

    每个指标独立采样 ``judge_samples`` 次，score 取成功采样均值并记录
    范围；采样在分析 deadline 内逐样本计时，超时样本按既有 TIMEOUT
    语义计入。
    """

    if timeout_seconds is not None and timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive or None")
    if judge_samples < 1:
        raise ValueError("judge_samples must be at least 1")
    if isinstance(case, DeepEvalAnalysisCase):
        case.analysis_trace.validate_digest()
    safe_model = _safe_model(judge_model)
    if judge is None:
        try:
            from .deepeval_metrics import DeepEvalSdkJudge

            judge = DeepEvalSdkJudge(judge_model=safe_model)
        except ImportError:
            return _unavailable_analysis(
                case,
                judge_model=safe_model,
                reason="DeepEval SDK is unavailable",
                agent_model=agent_model,
                judge_fingerprint=judge_fingerprint,
            )
        except Exception:
            return _unavailable_analysis(
                case,
                judge_model=safe_model,
                reason="DeepEval judge cannot be initialized",
                agent_model=agent_model,
                judge_fingerprint=judge_fingerprint,
            )

    deadline = (
        time.monotonic() + timeout_seconds if timeout_seconds is not None else None
    )
    metric_results: list[DeepEvalMetricResult] = []
    for metric_name in DEEPEVAL_METRIC_NAMES:
        observations: list[DeepEvalMetricObservation] = []
        for _ in range(judge_samples):
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    observations.append(
                        DeepEvalMetricObservation(
                            name=metric_name,
                            score=None,
                            reason="DeepEval analysis timed out",
                            status=AdapterStatus.TIMEOUT,
                        )
                    )
                else:
                    observations.append(
                        _evaluate_with_timeout(
                            judge,
                            case,
                            metric_name,
                            remaining,
                        )
                    )
            else:
                observations.append(_evaluate_direct(judge, case, metric_name))
        metric_results.append(
            _metric_result_from_samples(
                observations,
                case=case,
                judge_model=safe_model,
                metric_name=metric_name,
            )
        )
    return _analysis_from_metrics(
        case,
        judge_model=safe_model,
        metrics=tuple(metric_results),
        agent_model=agent_model,
        judge_fingerprint=judge_fingerprint,
    )


def _metric_result_from_samples(
    observations: Sequence[DeepEvalMetricObservation],
    *,
    case: DeepEvalCaseLike,
    judge_model: str,
    metric_name: str,
) -> DeepEvalMetricResult:
    """把同一指标的多轮采样聚合成均值±范围；失败语义沿用单样本路径。"""

    samples = len(observations)
    if samples == 1:
        return _metric_result_from_observation(
            observations[0],
            case=case,
            judge_model=judge_model,
            metric_name=metric_name,
        )
    sample_results = tuple(
        _metric_result_from_observation(
            observation,
            case=case,
            judge_model=judge_model,
            metric_name=metric_name,
        )
        for observation in observations
    )
    completed = tuple(
        result for result in sample_results if result.status is AdapterStatus.COMPLETED
    )
    if not completed:
        # 全部采样失败：沿用首个失败结果，只记录总采样次数。
        return sample_results[0].model_copy(update={"samples": samples})
    scores = tuple(
        float(result.score) for result in completed if result.score is not None
    )
    failures = samples - len(completed)
    reason = completed[0].reason
    if failures:
        note = f"{failures} 次采样失败"
        # 拼接后的 reason 可能超过 DeepEvalMetricResult.reason 的
        # max_length=320,须为注解预留空间:先截断基础 reason 再拼接,
        # 保证注解不被裁掉、整条分析不因校验失败降级。
        base = _safe_reason(reason) or ""
        if base:
            reserved = 320 - len(note) - 1
            base, _ = redact_text(base, max_length=max(1, reserved))
        reason = f"{base}；{note}" if base else note
    threshold = DEEPEVAL_METRIC_THRESHOLDS.get(metric_name)
    mean_score = sum(scores) / len(scores)
    return DeepEvalMetricResult(
        name=metric_name,
        score=mean_score,
        reason=reason,
        model=completed[0].model,
        input_digest=case.input_digest,
        status=AdapterStatus.COMPLETED,
        threshold=threshold,
        threshold_met=None if threshold is None else mean_score >= threshold,
        samples=samples,
        score_min=min(scores),
        score_max=max(scores),
    )


def analyze_verified_report(
    report: VerifiedEvaluationReport,
    *,
    input_digest: str,
    trajectory: DeepEvalTrajectory | None = None,
    analysis_trace: AnalysisTrace | None = None,
    judge_model: str,
    judge: DeepEvalJudge | None = None,
    timeout_seconds: float | None = 120.0,
    agent_model: str | None = None,
    judge_fingerprint: str | None = None,
    judge_samples: int = 3,
    input_preview: str | None = None,
    outcome_preview: str | None = None,
) -> VerifiedEvaluationReport:
    """将分析结果写回 report 的独立字段，保留原始正式结果对象。"""

    _ensure_telemetry_off()
    if analysis_trace is not None:
        analysis_trace.validate_digest()
        if report.task_result.task_id != analysis_trace.task_id:
            raise ValueError(
                "DeepEval Analysis Trace task_id does not match the report"
            )
        case: DeepEvalCaseLike = DeepEvalAnalysisCase(
            task_id=analysis_trace.task_id,
            input_digest=input_digest,
            analysis_trace=analysis_trace,
            expected_verdict=report.task_result.verdict,
            input_preview=input_preview,
            outcome_preview=outcome_preview,
        )
    elif trajectory is not None:
        if report.task_result.task_id != trajectory.task_id:
            raise ValueError("DeepEval trajectory task_id does not match the report")
        # 旧的直接调用接口仅用于既有 Opik/离线 fixture 测试；Verified
        # 生产路径必须传入已校验的 Analysis Trace。
        case = DeepEvalCase(
            task_id=trajectory.task_id,
            input_digest=input_digest,
            trajectory=trajectory,
            expected_verdict=report.task_result.verdict,
            input_preview=input_preview,
            outcome_preview=outcome_preview,
        )
    else:
        raise ValueError("DeepEval requires an Analysis Trace")
    analysis = analyze_deepeval_case(
        case,
        judge_model=judge_model,
        judge=judge,
        timeout_seconds=timeout_seconds,
        agent_model=agent_model,
        judge_fingerprint=judge_fingerprint,
        judge_samples=judge_samples,
    )
    analysis = analysis.model_copy(
        update={
            "extensions": {**analysis.extensions, "telemetry": "off"},
        }
    )
    return report.model_copy(update={"deepeval": analysis})


def _ensure_telemetry_off() -> None:
    """显式关停 DeepEval 上报：任何路径都不得携带 Confident AI 凭证。

    SDK 未配置 ``CONFIDENT_API_KEY`` 时 ``is_confident()`` 为 False、不会
    POST，但这是环境巧合而非不变量；此处把"不上报"固化为入口断言。
    """

    if os.environ.get("CONFIDENT_API_KEY") is not None:
        raise DeepEvalTelemetryError(
            "CONFIDENT_API_KEY is set; offline analysis never uploads to Confident AI"
        )
    try:
        from deepeval.confident.api import is_confident
    except ImportError:
        # SDK 未安装时不存在任何上报能力。
        return
    if is_confident():
        raise DeepEvalTelemetryError(
            "DeepEval Confident AI key is configured; offline analysis never uploads"
        )


def _evaluate_direct(
    judge: DeepEvalJudge,
    case: DeepEvalCaseLike,
    metric_name: str,
) -> DeepEvalMetricObservation:
    try:
        return judge.evaluate_metric(metric_name=metric_name, case=case)
    except TimeoutError:
        return DeepEvalMetricObservation(
            name=metric_name,
            score=None,
            reason="DeepEval metric timed out",
            status=AdapterStatus.TIMEOUT,
        )
    except ImportError:
        return DeepEvalMetricObservation(
            name=metric_name,
            score=None,
            reason="DeepEval metric is unavailable",
            status=AdapterStatus.UNAVAILABLE,
        )
    except Exception:
        return DeepEvalMetricObservation(
            name=metric_name,
            score=None,
            reason="DeepEval metric failed",
            status=AdapterStatus.FAILED,
        )


def _evaluate_with_timeout(
    judge: DeepEvalJudge,
    case: DeepEvalCaseLike,
    metric_name: str,
    timeout_seconds: float,
) -> DeepEvalMetricObservation:
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lion-deepeval")
    future = executor.submit(judge.evaluate_metric, metric_name=metric_name, case=case)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError:
        future.cancel()
        return DeepEvalMetricObservation(
            name=metric_name,
            score=None,
            reason="DeepEval metric timed out",
            status=AdapterStatus.TIMEOUT,
        )
    except ImportError:
        return DeepEvalMetricObservation(
            name=metric_name,
            score=None,
            reason="DeepEval metric is unavailable",
            status=AdapterStatus.UNAVAILABLE,
        )
    except TimeoutError:
        return DeepEvalMetricObservation(
            name=metric_name,
            score=None,
            reason="DeepEval metric timed out",
            status=AdapterStatus.TIMEOUT,
        )
    except Exception:
        return DeepEvalMetricObservation(
            name=metric_name,
            score=None,
            reason="DeepEval metric failed",
            status=AdapterStatus.FAILED,
        )
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _metric_result_from_observation(
    observation: DeepEvalMetricObservation,
    *,
    case: DeepEvalCaseLike,
    judge_model: str,
    metric_name: str,
) -> DeepEvalMetricResult:
    status = _observation_status(getattr(observation, "status", None))
    reason = _safe_reason(getattr(observation, "reason", None))
    model = _safe_model(getattr(observation, "model", None) or judge_model)
    input_digest = getattr(observation, "input_digest", None) or case.input_digest
    score = getattr(observation, "score", None)
    if getattr(observation, "name", metric_name) != metric_name:
        status = AdapterStatus.INVALID
        score = None
        reason = "DeepEval judge returned an unexpected metric name"
    elif input_digest != case.input_digest:
        status = AdapterStatus.INVALID
        score = None
        reason = "DeepEval judge returned a mismatched input digest"
    elif status is AdapterStatus.COMPLETED:
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            status = AdapterStatus.INVALID
            score = None
            reason = reason or "DeepEval metric returned no numeric score"
        elif not math.isfinite(float(score)) or not 0 <= float(score) <= 1:
            status = AdapterStatus.INVALID
            score = None
            reason = reason or "DeepEval metric returned an invalid score"
        else:
            score = float(score)
    else:
        score = None
    if status is not AdapterStatus.COMPLETED:
        score = None
        reason = reason or f"DeepEval metric status: {status.value}"
    reason = _with_sequence_reference(case, reason)
    threshold = DEEPEVAL_METRIC_THRESHOLDS.get(metric_name)
    threshold_met = (
        None
        if threshold is None
        else status is AdapterStatus.COMPLETED
        and score is not None
        and float(score) >= threshold
    )
    return DeepEvalMetricResult(
        name=metric_name,
        score=score,
        reason=reason,
        model=model,
        input_digest=case.input_digest,
        status=status,
        threshold=threshold,
        threshold_met=threshold_met,
    )


def _analysis_from_metrics(
    case: DeepEvalCaseLike,
    *,
    judge_model: str,
    metrics: tuple[DeepEvalMetricResult, ...],
    agent_model: str | None = None,
    judge_fingerprint: str | None = None,
) -> DeepEvalAnalysis:
    statuses = tuple(metric.status for metric in metrics)
    if all(status is AdapterStatus.COMPLETED for status in statuses):
        status = DeepEvalAnalysisStatus.COMPLETED
        reason = None
        failure_source = None
    elif any(status is AdapterStatus.COMPLETED for status in statuses):
        status = DeepEvalAnalysisStatus.PARTIAL
        reason = (
            _first_metric_reason(metrics) or "DeepEval analysis contains failed metrics"
        )
        failure_source = FailureSource.DEEPEVAL
    elif all(
        status in {AdapterStatus.UNAVAILABLE, AdapterStatus.BLOCKED}
        for status in statuses
    ):
        status = DeepEvalAnalysisStatus.UNAVAILABLE
        reason = _first_metric_reason(metrics) or "DeepEval analysis is unavailable"
        failure_source = FailureSource.DEEPEVAL
    elif all(
        status
        in {
            AdapterStatus.TIMEOUT,
            AdapterStatus.UNAVAILABLE,
            AdapterStatus.BLOCKED,
        }
        for status in statuses
    ) and any(status is AdapterStatus.TIMEOUT for status in statuses):
        status = DeepEvalAnalysisStatus.TIMEOUT
        reason = _first_metric_reason(metrics) or "DeepEval analysis timed out"
        failure_source = FailureSource.DEEPEVAL
    else:
        status = DeepEvalAnalysisStatus.FAILED
        reason = _first_metric_reason(metrics) or "DeepEval analysis failed"
        failure_source = FailureSource.DEEPEVAL
    return DeepEvalAnalysis(
        task_id=case.task_id,
        status=status,
        judge_model=judge_model,
        input_digest=case.input_digest,
        trajectory_digest=_case_trace_digest(case),
        metrics=metrics,
        agent_model=agent_model,
        judge_fingerprint=judge_fingerprint,
        score_gate=_score_gate(metrics),
        failure_source=failure_source,
        reason=reason,
    )


def _score_gate(metrics: tuple[DeepEvalMetricResult, ...]) -> DeepEvalScoreGate | None:
    """对已评分指标做阈值对照；无已评分指标(全失败/超时/不可用)返回 None。"""

    scored = tuple(
        metric
        for metric in metrics
        if metric.status is AdapterStatus.COMPLETED and metric.threshold is not None
    )
    if not scored:
        return None
    passed_metrics = sum(1 for metric in scored if metric.threshold_met is True)
    threshold = scored[0].threshold
    assert threshold is not None  # scored 成员已保证 threshold 非 None
    return DeepEvalScoreGate(
        passed=passed_metrics == len(scored),
        passed_metrics=passed_metrics,
        evaluated_metrics=len(scored),
        reason=(
            f"全部 {len(scored)} 项已评分指标达阈值(阈值 {threshold:.4g})"
            if passed_metrics == len(scored)
            else f"{len(scored)} 项已评分指标中 {passed_metrics} 项达阈值(阈值 {threshold:.4g})"
        ),
    )


def _unavailable_analysis(
    case: DeepEvalCaseLike,
    *,
    judge_model: str,
    reason: str,
    agent_model: str | None = None,
    judge_fingerprint: str | None = None,
) -> DeepEvalAnalysis:
    metrics = tuple(
        DeepEvalMetricResult(
            name=metric_name,
            score=None,
            reason=reason,
            model=judge_model,
            input_digest=case.input_digest,
            status=AdapterStatus.UNAVAILABLE,
        )
        for metric_name in DEEPEVAL_METRIC_NAMES
    )
    return DeepEvalAnalysis(
        task_id=case.task_id,
        status=DeepEvalAnalysisStatus.UNAVAILABLE,
        judge_model=judge_model,
        input_digest=case.input_digest,
        trajectory_digest=_case_trace_digest(case),
        metrics=metrics,
        agent_model=agent_model,
        judge_fingerprint=judge_fingerprint,
        failure_source=FailureSource.DEEPEVAL,
        reason=reason,
    )


def _observation_status(value: Any) -> AdapterStatus:
    if isinstance(value, AdapterStatus):
        return value
    try:
        return AdapterStatus(str(value))
    except ValueError:
        return AdapterStatus.INVALID


def _first_metric_reason(metrics: Sequence[DeepEvalMetricResult]) -> str | None:
    return next((metric.reason for metric in metrics if metric.reason), None)


def _safe_model(value: str) -> str:
    model, _ = redact_text(str(value), max_length=256)
    return model.strip() or "unknown"


def _safe_reason(value: Any) -> str | None:
    if value is None:
        return None
    reason, _ = redact_text(str(value), max_length=320)
    return reason.strip() or None


def _case_trace_digest(case: DeepEvalCaseLike) -> str:
    if isinstance(case, DeepEvalAnalysisCase):
        return case.analysis_trace.trace_digest
    return case.trajectory.trace_digest


def _with_sequence_reference(
    case: DeepEvalCaseLike,
    reason: str | None,
) -> str | None:
    """让语义指标 reason 至少能回指一条受控事件序列。"""

    if not isinstance(case, DeepEvalAnalysisCase):
        return reason
    if not case.analysis_trace.events:
        return reason
    if reason and "[seq=" in reason:
        return reason
    sequence = case.analysis_trace.events[0].sequence
    suffix = f" [seq={sequence}]"
    base = reason or "DeepEval metric completed"
    safe_base, _ = redact_text(base, max_length=max(1, 320 - len(suffix)))
    return f"{safe_base.rstrip()} {suffix}"[:320]


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
    """从 TraceEvent 仅投影 digest/工具元数据，不复制 summary 或正文。

    投影前先按事件类型升采样（丢弃 ``NOISE_EVENT_TYPES`` 的高频流式
    快照），再截断到上限；过滤只改变 judge 所见序列，不触碰原始持久化。
    """

    if max_events < 1 or max_events > MAX_TRAJECTORY_EVENTS:
        raise ValueError(f"max_events must be between 1 and {MAX_TRAJECTORY_EVENTS}")
    visible = tuple(
        event for event in trace_events if event.event_type not in NOISE_EVENT_TYPES
    )[:max_events]
    projected: list[DeepEvalTrajectoryEvent] = []
    for event in visible:
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
                started_at=getattr(event, "started_at", None),
                finished_at=getattr(event, "finished_at", None),
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
    "DEEPEVAL_METRIC_NAMES",
    "DEEPEVAL_METRIC_THRESHOLDS",
    "DEEPEVAL_RESULT_SCHEMA_VERSION",
    "NOISE_EVENT_TYPES",
    "DeepEvalAnalysisCase",
    "DeepEvalJudge",
    "DeepEvalMetricFixture",
    "DeepEvalMetricObservation",
    "DeepEvalResultError",
    "DeepEvalResultFixture",
    "DeepEvalSchemaError",
    "DeepEvalTelemetryError",
    "DeepEvalTimeoutError",
    "analyze_deepeval_case",
    "analyze_verified_report",
    "build_deepeval_trajectory",
    "deepeval_analysis_json",
    "map_deepeval_status",
    "parse_deepeval_analysis",
)
