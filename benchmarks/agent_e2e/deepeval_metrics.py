"""DeepEval 固定指标和脱敏 trajectory 的 benchmark-only 适配。"""

from __future__ import annotations

import json
import math
from typing import Any

from .deepeval_analysis import DEEPEVAL_METRIC_NAMES, DeepEvalMetricObservation
from .models import DeepEvalCase
from .trace import redact_text

DEEPEVAL_SDK_VERSION = "4.2.0"
MAX_DEEPEVAL_TEXT = 12_000
TRAJECTORY_QUALITY_EVALUATION_STEPS = (
    "Assess whether the observed execution makes measurable progress toward the task.",
    "Assess whether the selected tools and their ordering are appropriate from the redacted trajectory metadata.",
    "Penalize repeated or looping actions, unnecessary detours, and premature termination.",
    "Assess whether the observed final state provides evidence for a coherent outcome without using private verifier data.",
)


class DeepEvalMetricError(RuntimeError):
    """DeepEval SDK 或单项 metric 执行失败。"""


class DeepEvalDependencyError(DeepEvalMetricError):
    """DeepEval optional dependency 不可用或 API 不符合固定版本。"""


class DeepEvalEvaluationError(DeepEvalMetricError):
    """DeepEval metric 无法从受控输入得到结果。"""


def build_deepeval_metrics(*, judge_model: str) -> tuple[object, ...]:
    """构造首版固定的三个 DeepEval metric，不在导入时加载 optional SDK。"""

    if not judge_model.strip():
        raise ValueError("judge_model must not be empty")
    try:
        from deepeval.metrics import GEval, StepEfficiencyMetric, TaskCompletionMetric
        from deepeval.test_case import SingleTurnParams
    except ImportError as error:
        raise DeepEvalDependencyError("DeepEval SDK is unavailable") from error
    try:
        return (
            TaskCompletionMetric(
                threshold=None,
                model=judge_model,
                include_reason=True,
                async_mode=False,
            ),
            StepEfficiencyMetric(
                threshold=None,
                model=judge_model,
                include_reason=True,
                async_mode=False,
            ),
            GEval(
                name="TrajectoryQuality",
                evaluation_steps=TRAJECTORY_QUALITY_EVALUATION_STEPS,
                evaluation_params=[
                    SingleTurnParams.INPUT,
                    SingleTurnParams.ACTUAL_OUTPUT,
                ],
                threshold=None,
                model=judge_model,
                async_mode=False,
            ),
        )
    except Exception as error:
        raise DeepEvalDependencyError(
            "DeepEval SDK metric API is incompatible"
        ) from error


def deepeval_case_to_test_case(case: DeepEvalCase) -> object:
    """把固定 case 投影为不含正文的 DeepEval ``LLMTestCase``。"""

    try:
        from deepeval.test_case import LLMTestCase, ToolCall
    except ImportError as error:
        raise DeepEvalDependencyError("DeepEval SDK is unavailable") from error
    tools_called = [
        ToolCall(name=safe_text(event.tool_name, max_length=160))
        for event in case.trajectory.events
        if event.tool_name
    ]
    return LLMTestCase(
        input=_case_input(case),
        actual_output=_trajectory_output(case),
        tools_called=tools_called,
    )


class DeepEvalSdkJudge:
    """使用冻结脱敏 trajectory 的 DeepEval judge，不重新运行 Lion Agent。"""

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
        case: DeepEvalCase,
    ) -> DeepEvalMetricObservation:
        """评估一项固定 metric，并只返回受控摘要。"""

        metric = self._metrics.get(metric_name)
        if metric is None:
            raise ValueError(f"unsupported DeepEval metric: {metric_name}")
        try:
            if metric_name in DEEPEVAL_METRIC_NAMES[:2]:
                _evaluate_trajectory_metric(metric, case)
            else:
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


def _evaluate_trajectory_metric(metric: object, case: DeepEvalCase) -> None:
    """按 DeepEval 官方 trace/evals_iterator 路径分析已有 trajectory。"""

    try:
        from deepeval.dataset import EvaluationDataset, Golden
        from deepeval.evaluate import AsyncConfig
        from deepeval.tracing import observe, update_current_trace
    except ImportError as error:
        raise DeepEvalDependencyError("DeepEval trajectory API is unavailable") from error

    output = _trajectory_output(case)
    tools_called = [
        _make_tool_call(event.tool_name)
        for event in case.trajectory.events
        if event.tool_name
    ]

    @observe(type="agent", name="lion_redacted_trajectory")
    def replay(_: str) -> str:
        update_current_trace(
            name="lion-redacted-trajectory",
            input=_case_input(case),
            output=output,
            tools_called=tools_called,
            metadata={
                "lion_task_id": safe_text(case.task_id, max_length=160),
                "trajectory_digest": case.trajectory.trace_digest,
            },
            tags=["lion", "agent-e2e"],
        )
        return output

    dataset = EvaluationDataset(goldens=[Golden(input=_case_input(case))])
    for golden in dataset.evals_iterator(
        metrics=[metric],
        async_config=AsyncConfig(run_async=False),
    ):
        replay(golden.input)


def _make_tool_call(tool_name: str) -> object:
    try:
        from deepeval.test_case import ToolCall
    except ImportError as error:
        raise DeepEvalDependencyError("DeepEval SDK is unavailable") from error
    return ToolCall(name=safe_text(tool_name, max_length=160))


def _case_input(case: DeepEvalCase) -> str:
    return (
        f"task_id={safe_text(case.task_id, max_length=160)} "
        f"input_digest={case.input_digest}"
    )


def _trajectory_output(case: DeepEvalCase) -> str:
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
    serialized = json.dumps(
        {"trace_digest": case.trajectory.trace_digest, "events": events},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return serialized[:MAX_DEEPEVAL_TEXT]


def safe_text(value: str, *, max_length: int) -> str:
    """限制并脱敏 SDK 结果中的短文本。"""

    safe, _ = redact_text(str(value), max_length=max_length)
    return safe.strip()


__all__ = (
    "DEEPEVAL_SDK_VERSION",
    "MAX_DEEPEVAL_TEXT",
    "TRAJECTORY_QUALITY_EVALUATION_STEPS",
    "DeepEvalDependencyError",
    "DeepEvalEvaluationError",
    "DeepEvalMetricError",
    "DeepEvalSdkJudge",
    "build_deepeval_metrics",
    "deepeval_case_to_test_case",
    "safe_text",
)
