"""DeepEval 固定指标和脱敏 trajectory 的 benchmark-only 适配。"""

from __future__ import annotations

import json
import math
from typing import Any

from .analysis_trace import AnalysisTrace
from .deepeval_analysis import (
    DEEPEVAL_METRIC_NAMES,
    DEEPEVAL_METRIC_THRESHOLDS,
    DeepEvalAnalysisCase,
    DeepEvalCaseLike,
    DeepEvalMetricObservation,
)
from .models import AdapterStatus, DeepEvalCase
from .trace import redact_text

DEEPEVAL_SDK_VERSION = "4.2.0"
MAX_DEEPEVAL_TEXT = 12_000
TOOL_DECISION_QUALITY_EVALUATION_STEPS = (
    "Assess whether each selected tool is relevant to the public task and the observed context.",
    "Assess whether the order of tool calls makes progress without unrelated detours.",
    "Assess whether the next tool action responds appropriately to an observed tool error.",
    "Cite the relevant ordered event using its [seq=N] marker and do not infer hidden reasoning.",
)
# 保留导出名称，避免报告/调用方把评价步骤误认为新的指标；实际 metric
# 只使用上面的 ToolDecisionQuality rubric。
TRAJECTORY_QUALITY_EVALUATION_STEPS = TOOL_DECISION_QUALITY_EVALUATION_STEPS


class DeepEvalMetricError(RuntimeError):
    """DeepEval SDK 或单项 metric 执行失败。"""


class DeepEvalDependencyError(DeepEvalMetricError):
    """DeepEval optional dependency 不可用或 API 不符合固定版本。"""


class DeepEvalEvaluationError(DeepEvalMetricError):
    """DeepEval metric 无法从受控输入得到结果。"""


def build_deepeval_metrics(*, judge_model: str) -> tuple[object, ...]:
    """构造首版固定的两个 action metric，不在导入时加载 optional SDK。"""

    if not judge_model.strip():
        raise ValueError("judge_model must not be empty")
    try:
        from deepeval.metrics import ArgumentCorrectnessMetric, GEval
        from deepeval.test_case import SingleTurnParams
    except ImportError as error:
        raise DeepEvalDependencyError("DeepEval SDK is unavailable") from error
    try:
        return (
            ArgumentCorrectnessMetric(
                threshold=DEEPEVAL_METRIC_THRESHOLDS["ArgumentCorrectnessMetric"],
                model=judge_model,
                include_reason=True,
                async_mode=False,
            ),
            GEval(
                name="ToolDecisionQuality",
                evaluation_steps=TOOL_DECISION_QUALITY_EVALUATION_STEPS,
                evaluation_params=[
                    SingleTurnParams.INPUT,
                    SingleTurnParams.ACTUAL_OUTPUT,
                ],
                threshold=DEEPEVAL_METRIC_THRESHOLDS["ToolDecisionQuality"],
                model=judge_model,
                async_mode=False,
            ),
        )
    except Exception as error:
        raise DeepEvalDependencyError(
            "DeepEval SDK metric API is incompatible"
        ) from error


def deepeval_case_to_test_case(case: DeepEvalAnalysisCase) -> object:
    """把安全语义 case 投影为 DeepEval ``LLMTestCase``。"""

    trace = _require_analysis_trace(case)
    try:
        from deepeval.test_case import LLMTestCase
    except ImportError as error:
        raise DeepEvalDependencyError("DeepEval SDK is unavailable") from error
    tools_called = [
        _make_tool_call(event.tool_name, event.safe_data)
        for event in trace.events
        if event.kind == "tool_call"
    ]
    return LLMTestCase(
        input=_case_input(case),
        actual_output=_analysis_trace_output(trace),
        tools_called=tools_called,
    )


class DeepEvalSdkJudge:
    """使用冻结安全 Analysis Trace 的 DeepEval judge，不重新运行 Lion Agent。"""

    def __init__(self, *, judge_model: str) -> None:
        self.judge_model = safe_text(judge_model, max_length=256)
        if not self.judge_model:
            raise ValueError("judge_model must not be empty")
        self._metrics = dict(
            zip(
                DEEPEVAL_METRIC_NAMES,
                build_deepeval_metrics(judge_model=self.judge_model),
                strict=True,
            )
        )

    def evaluate_metric(
        self,
        *,
        metric_name: str,
        case: DeepEvalCaseLike,
    ) -> DeepEvalMetricObservation:
        """评估一项固定 metric，并只返回受控摘要。"""

        metric = self._metrics.get(metric_name)
        if metric is None:
            raise ValueError(f"unsupported DeepEval metric: {metric_name}")
        trace = _require_analysis_trace(case)
        if not any(event.kind == "tool_call" for event in trace.events):
            return DeepEvalMetricObservation(
                name=metric_name,
                score=None,
                reason="Analysis Trace contains no tool calls; metric unavailable",
                model=self.judge_model,
                input_digest=case.input_digest,
                status=AdapterStatus.UNAVAILABLE,
            )
        if not isinstance(case, DeepEvalAnalysisCase):
            raise DeepEvalDependencyError(
                "DeepEval requires a validated Analysis Trace"
            )
        try:
            measure = getattr(metric, "measure", None)
            if not callable(measure):
                raise DeepEvalEvaluationError(
                    f"DeepEval metric has no measure method: {metric_name}"
                )
            measure(deepeval_case_to_test_case(case))
        except DeepEvalMetricError:
            raise
        except Exception as error:
            raise DeepEvalEvaluationError(
                f"DeepEval metric failed: {metric_name}"
            ) from error
        score = getattr(metric, "score", None)
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            raise DeepEvalEvaluationError(
                f"DeepEval metric returned no numeric score: {metric_name}"
            )
        score = float(score)
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise DeepEvalEvaluationError(
                f"DeepEval metric returned an invalid score: {metric_name}"
            )
        reason = getattr(metric, "reason", None)
        safe_reason = safe_text(str(reason), max_length=320) if reason else None
        return DeepEvalMetricObservation(
            name=metric_name,
            score=score,
            reason=safe_reason,
            model=self.judge_model,
            input_digest=case.input_digest,
        )


def _make_tool_call(tool_name: str, input_parameters: dict[str, Any]) -> object:
    try:
        from deepeval.test_case import ToolCall
    except ImportError as error:
        raise DeepEvalDependencyError("DeepEval SDK is unavailable") from error
    try:
        return ToolCall(
            name=safe_text(tool_name, max_length=160),
            input_parameters=dict(input_parameters),
        )
    except Exception as error:
        raise DeepEvalDependencyError(
            "DeepEval ToolCall API does not accept safe input_parameters"
        ) from error


def _case_input(case: DeepEvalCaseLike) -> str:
    parts = [
        f"task_id={safe_text(case.task_id, max_length=160)}",
        f"input_digest={case.input_digest}",
    ]
    if case.input_preview:
        parts.append(
            f"task_description={safe_text(case.input_preview, max_length=4000)}"
        )
    return " ".join(parts)


def _analysis_trace_output(trace: AnalysisTrace) -> str:
    """生成带序列标记的受控 call/result 文本。"""

    events = [
        {
            "seq": event.sequence,
            "kind": event.kind,
            "tool": safe_text(event.tool_name, max_length=160),
            "action": safe_text(event.action, max_length=64),
            "safe_data": event.safe_data,
        }
        for event in trace.events
    ]
    serialized_events = [
        f"[seq={event['seq']}] {event['kind']} "
        f"tool={event['tool']} action={event['action']} "
        f"safe_data={json.dumps(event['safe_data'], ensure_ascii=False, sort_keys=True, separators=(',', ':'))}"
        for event in events
    ]
    output = "\n".join(serialized_events)
    if not output:
        output = f"trace_digest={trace.trace_digest}; no tool calls"
    return output[:MAX_DEEPEVAL_TEXT]


def _trajectory_output(case: DeepEvalCase) -> str:
    """保留旧 fixture 的受控文本投影；生产 SDK 只走 Analysis Trace。"""

    events: list[dict[str, Any]] = []
    for event in case.trajectory.events:
        events.append(
            {
                "sequence": event.sequence,
                "event_type": safe_text(event.event_type, max_length=160),
                "tool_name": safe_text(event.tool_name, max_length=160)
                if event.tool_name
                else None,
                "payload_digest": event.payload_digest,
                "argument_digest": event.argument_digest,
                "workspace_fingerprint": event.workspace_fingerprint,
                "started_at": event.started_at.isoformat()
                if event.started_at
                else None,
                "finished_at": event.finished_at.isoformat()
                if event.finished_at
                else None,
            }
        )
    payload: dict[str, Any] = {
        "trace_digest": case.trajectory.trace_digest,
        "events": events,
    }
    if case.outcome_preview:
        payload["outcome_preview"] = safe_text(case.outcome_preview, max_length=2000)
    # 结果预览放在 events 之前:超长轨迹被截断时,judge 仍能看到最终结果;
    # 截断只影响事件尾部,不破坏预览字段。
    ordered: dict[str, Any] = {}
    if case.outcome_preview:
        ordered["outcome_preview"] = payload.pop("outcome_preview")
    ordered["trace_digest"] = payload.pop("trace_digest")
    ordered["events"] = payload.pop("events")
    serialized = json.dumps(
        ordered, ensure_ascii=False, sort_keys=False, separators=(",", ":")
    )
    return serialized[:MAX_DEEPEVAL_TEXT]


def _require_analysis_trace(case: DeepEvalCaseLike) -> AnalysisTrace:
    trace = getattr(case, "analysis_trace", None)
    if not isinstance(trace, AnalysisTrace):
        raise DeepEvalDependencyError("DeepEval requires a validated Analysis Trace")
    trace.validate_digest()
    return trace


def safe_text(value: str, *, max_length: int) -> str:
    """限制并脱敏 SDK 结果中的短文本。"""

    safe, _ = redact_text(str(value), max_length=max_length)
    return safe.strip()


__all__ = (
    "DEEPEVAL_SDK_VERSION",
    "MAX_DEEPEVAL_TEXT",
    "TOOL_DECISION_QUALITY_EVALUATION_STEPS",
    "TRAJECTORY_QUALITY_EVALUATION_STEPS",
    "DeepEvalDependencyError",
    "DeepEvalEvaluationError",
    "DeepEvalMetricError",
    "DeepEvalSdkJudge",
    "build_deepeval_metrics",
    "deepeval_case_to_test_case",
    "safe_text",
)
