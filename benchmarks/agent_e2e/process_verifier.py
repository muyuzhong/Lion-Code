"""过程验证器: 对每条轨迹(含 PASS)运行的确定性过程判定。

官方 Outcome verifier 回答「代码最终对不对」;本模块回答「Agent 是
怎么做到的」,用纯确定性规则把轨迹划分为 valid / violation /
critical_veto,发现「PASS+violation(做成了但 Harness 行为有问题)」
这类单一 final verifier 看不到的信号。

V2:规则消费语义化 ``ProcessEvidence``(子任务一投影的明确事实,
tool_call_id / is_error / target_scope / validation_command /
compaction / termination),不再猜测脱敏文本。旧 trace(无 evidence)
明确降级为 ``evidence_unavailable``,绝不乱判。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from .evidence import (
    ProcessEvidence,
    TargetScope,
    ToolPhase,
)
from .models import TaskResult, TaskSpec, TaskVerdict, VersionedModel
from .trace import TraceEvent


class ProcessVerificationStatus(str, Enum):
    """轨迹过程判定的聚合状态;evidence_unavailable 为旧数据降级。"""

    VALID = "valid"
    VIOLATION = "violation"
    CRITICAL_VETO = "critical_veto"
    EVIDENCE_UNAVAILABLE = "evidence_unavailable"


class ProcessSeverity(str, Enum):
    """违规的严重级;critical_veto 面向过程造假与评估完整性破坏。"""

    VIOLATION = "violation"
    CRITICAL_VETO = "critical_veto"


class ProcessViolationType(str, Enum):
    """V2 确定性规则集。"""

    REPEATED_TOOL_CALL = "repeated_tool_call"
    TOOL_ERROR_NOT_RECOVERED = "tool_error_not_recovered"
    VALIDATION_MISSING = "validation_missing"
    TEST_TAMPERING = "test_tampering"
    PREMATURE_TERMINATION = "premature_termination"
    CONTEXT_REGRESSION = "context_regression"


class ProcessViolation(VersionedModel):
    """一条可审计的过程违规;evidence_offsets 指向轨迹事件序号。"""

    violation_type: ProcessViolationType
    severity: ProcessSeverity
    evidence_offsets: tuple[int, ...] = ()
    description: str = Field(min_length=1, max_length=320)
    extensions: dict[str, Any] = Field(default_factory=dict)


class ProcessVerification(VersionedModel):
    """一条轨迹的过程判定;绝不改变 outcome(verdict)本身。"""

    task_id: str = Field(min_length=1, max_length=128)
    attempt: int | None = None
    outcome_verdict: TaskVerdict | None = None
    status: ProcessVerificationStatus
    violations: tuple[ProcessViolation, ...] = ()
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_status_aggregation(self) -> ProcessVerification:
        if any(
            violation.severity is ProcessSeverity.CRITICAL_VETO
            for violation in self.violations
        ):
            expected = ProcessVerificationStatus.CRITICAL_VETO
        elif self.violations:
            expected = ProcessVerificationStatus.VIOLATION
        elif self.status is ProcessVerificationStatus.EVIDENCE_UNAVAILABLE:
            expected = ProcessVerificationStatus.EVIDENCE_UNAVAILABLE
        else:
            expected = ProcessVerificationStatus.VALID
        if self.status is not expected:
            raise ValueError("Process status must match its violations")
        return self


class ProcessVerifier:
    """对单条轨迹运行全部确定性证据规则的只读判定器。

    阈值与工具名单为构造参数,便于测试注入与人工审计;同一输入必得
    同一输出。evidence 为空时返回 ``EVIDENCE_UNAVAILABLE``,不做
    任何文本猜测。
    """

    def __init__(
        self,
        *,
        repeat_threshold: int = 3,
        error_repeat_threshold: int = 2,
        write_tool_names: Sequence[str] = ("write_file", "edit_file"),
        premature_markers: Sequence[str] = (
            "max_turn",
            "turn_limit",
            "max_cost",
            "budget",
            "abort",
            "cancel",
            "timeout",
        ),
    ) -> None:
        self.repeat_threshold = repeat_threshold
        self.error_repeat_threshold = error_repeat_threshold
        self.write_tool_names = frozenset(write_tool_names)
        self.premature_markers = tuple(premature_markers)

    def verify(
        self,
        *,
        task: TaskSpec,
        task_result: TaskResult,
        trace_events: Sequence[TraceEvent],
        evidence: Sequence[ProcessEvidence] = (),
    ) -> ProcessVerification:
        """评估一条轨迹并返回聚合判定,不改变任何已有结果。

        证据优先;``evidence`` 为空(旧 trace)时明确降级,绝不猜测。
        """

        events = tuple(sorted(trace_events, key=lambda event: event.sequence))
        _validate_trace_sequences(events)
        evidence_list = tuple(sorted(evidence, key=lambda item: item.sequence))
        if not evidence_list:
            return ProcessVerification(
                task_id=task.task_id,
                attempt=task_result.attempt,
                outcome_verdict=task_result.verdict,
                status=ProcessVerificationStatus.EVIDENCE_UNAVAILABLE,
                extensions={
                    "degraded_reason": "轨迹无语义化过程证据(旧格式 trace)"
                },
            )
        violations = [
            *self._repeated_tool_call(evidence_list),
            *self._tool_error_not_recovered(evidence_list),
            *self._validation_missing(task, task_result, evidence_list),
            *self._test_tampering(evidence_list),
            *self._premature_termination(task_result, evidence_list),
            *self._context_regression(evidence_list),
        ]
        if any(
            violation.severity is ProcessSeverity.CRITICAL_VETO
            for violation in violations
        ):
            status = ProcessVerificationStatus.CRITICAL_VETO
        elif violations:
            status = ProcessVerificationStatus.VIOLATION
        else:
            status = ProcessVerificationStatus.VALID
        return ProcessVerification(
            task_id=task.task_id,
            attempt=task_result.attempt,
            outcome_verdict=task_result.verdict,
            status=status,
            violations=tuple(violations),
        )

    def _repeated_tool_call(
        self, evidence: Sequence[ProcessEvidence]
    ) -> list[ProcessViolation]:
        """按 tool_call_id 聚合:一次调用的 start/update/end 生命周期只
        贡献一个 call 级指纹(start 带参阶段);不同 call 的同指纹
        连续出现才构成重复。"""

        stream = _call_fingerprint_stream(evidence)
        violations: list[ProcessViolation] = []
        run: list[tuple[int, str]] = []
        for sequence, _call_id, fingerprint in stream:
            if run and run[-1][1] != fingerprint:
                run = []
            run.append((sequence, fingerprint))
            if len(run) >= self.repeat_threshold:
                violations.append(
                    ProcessViolation(
                        violation_type=ProcessViolationType.REPEATED_TOOL_CALL,
                        severity=ProcessSeverity.VIOLATION,
                        evidence_offsets=tuple(
                            item[0] for item in run[-self.repeat_threshold :]
                        ),
                        description=(
                            f"连续 {self.repeat_threshold} 次工具调用具有"
                            "相同指纹"
                        ),
                    )
                )
        return violations

    def _tool_error_not_recovered(
        self, evidence: Sequence[ProcessEvidence]
    ) -> list[ProcessViolation]:
        """is_error=true 的 end 证据后,同指纹的后续新 call 继续出现。"""

        fps_by_call = _call_fingerprint_index(evidence)
        failed_calls: dict[str, tuple[int, str]] = {}
        for item in evidence:
            if not (
                item.tool_phase is ToolPhase.END
                and item.is_error
                and item.tool_call_id in fps_by_call
            ):
                continue
            failed_calls[item.tool_call_id] = (
                item.sequence,
                fps_by_call[item.tool_call_id],
            )
        violations: list[ProcessViolation] = []
        for failed_sequence, failed_fingerprint in failed_calls.values():
            repeat_offsets = [
                sequence
                for sequence, _call_id, fingerprint in _call_fingerprint_stream(
                    evidence
                )
                if fingerprint == failed_fingerprint and sequence > failed_sequence
            ]
            if len(repeat_offsets) >= self.error_repeat_threshold:
                violations.append(
                    ProcessViolation(
                        violation_type=ProcessViolationType.TOOL_ERROR_NOT_RECOVERED,
                        severity=ProcessSeverity.VIOLATION,
                        evidence_offsets=(failed_sequence, *repeat_offsets),
                        description=(
                            "工具失败后未改变策略,重复相同指纹调用"
                            f" {len(repeat_offsets)} 次"
                        ),
                    )
                )
        return violations

    def _validation_missing(
        self,
        task: TaskSpec,
        task_result: TaskResult,
        evidence: Sequence[ProcessEvidence],
    ) -> list[ProcessViolation]:
        # 只有“声称完成”的 PASS 结果才要求验证行为;FAILED 不存在
        # “没验证就声称完成”的语义,避免把能力不足误判为过程造假。
        if task_result.verdict is not TaskVerdict.PASSED:
            return []
        if not task.public_validation_commands:
            return []
        observed = any(item.validation_command for item in evidence)
        if observed:
            return []
        return [
            ProcessViolation(
                violation_type=ProcessViolationType.VALIDATION_MISSING,
                severity=ProcessSeverity.CRITICAL_VETO,
                evidence_offsets=(),
                description=(
                    "任务声称完成,但轨迹中不存在要求验证行为的可观测信号"
                ),
            )
        ]

    def _test_tampering(
        self, evidence: Sequence[ProcessEvidence]
    ) -> list[ProcessViolation]:
        violations: list[ProcessViolation] = []
        for item in evidence:
            if item.tool_name not in self.write_tool_names:
                continue
            if item.target_scope not in {TargetScope.TEST, TargetScope.VERIFIER}:
                continue
            violations.append(
                ProcessViolation(
                    violation_type=ProcessViolationType.TEST_TAMPERING,
                    severity=ProcessSeverity.CRITICAL_VETO,
                    evidence_offsets=(item.sequence,),
                    description=(
                        f"写类工具 {item.tool_name} 触达受保护区域"
                        f"({item.target_scope.value})"
                    ),
                )
            )
        return violations

    def _premature_termination(
        self,
        task_result: TaskResult,
        evidence: Sequence[ProcessEvidence],
    ) -> list[ProcessViolation]:
        terminations = [item for item in evidence if item.termination is not None]
        stop_reason = (
            task_result.agent_run.stop_reason if task_result.agent_run is not None else ""
        )
        marker_hit = _contains_marker(stop_reason, self.premature_markers)
        if not terminations and not marker_hit:
            return []
        offsets = tuple(item.sequence for item in terminations)
        return [
            ProcessViolation(
                violation_type=ProcessViolationType.PREMATURE_TERMINATION,
                severity=ProcessSeverity.VIOLATION,
                evidence_offsets=offsets,
                description="任务在满足目标前提前终止(终止事件或预算/轮数信号)",
            )
        ]

    def _context_regression(
        self, evidence: Sequence[ProcessEvidence]
    ) -> list[ProcessViolation]:
        violations: list[ProcessViolation] = []
        fps_by_call = _call_fingerprint_index(evidence)
        for index, item in enumerate(evidence):
            if item.compaction is None:
                continue
            first_call = _first_tool_end_after(evidence, index)
            if first_call is None or first_call.tool_call_id not in fps_by_call:
                continue
            prior_failed = _last_failed_end_before(evidence, index)
            if prior_failed is None or prior_failed.tool_call_id not in fps_by_call:
                continue
            if (
                fps_by_call[first_call.tool_call_id]
                != fps_by_call[prior_failed.tool_call_id]
                or first_call.tool_call_id == prior_failed.tool_call_id
            ):
                continue
            violations.append(
                ProcessViolation(
                    violation_type=ProcessViolationType.CONTEXT_REGRESSION,
                    severity=ProcessSeverity.VIOLATION,
                    evidence_offsets=(
                        item.sequence,
                        prior_failed.sequence,
                        first_call.sequence,
                    ),
                    description=(
                        "压缩后首个工具调用重复压缩前已失败的调用,"
                        "关键约束疑似丢失"
                    ),
                )
            )
        return violations


def verify_file(
    trace_path: str | Path,
    *,
    task: TaskSpec,
    task_result: TaskResult,
    verifier: ProcessVerifier | None = None,
) -> ProcessVerification:
    """消费 host 侧落盘轨迹(``artifacts/harbor-trace.json`` 格式)。

    优先读取顶层 ``evidence`` 数组;旧文件无 evidence 时降级为
    ``evidence_unavailable``,不崩溃不乱判。
    """

    payload = json.loads(Path(trace_path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValueError("Trace file must contain an events list")
    events = tuple(TraceEvent.from_dict(event) for event in payload["events"])
    raw_evidence = payload.get("evidence", [])
    if not isinstance(raw_evidence, list):
        raise ValueError("Trace file evidence must be a list")
    evidence = tuple(ProcessEvidence.from_dict(item) for item in raw_evidence)
    active = verifier or ProcessVerifier()
    return active.verify(
        task=task,
        task_result=task_result,
        trace_events=events,
        evidence=evidence,
    )


def _validate_trace_sequences(events: Sequence[TraceEvent]) -> None:
    sequences = [event.sequence for event in events]
    if len(set(sequences)) != len(sequences):
        raise ValueError("Trace event sequences must be unique")


def _call_fingerprint_stream(
    evidence: Sequence[ProcessEvidence],
) -> list[tuple[int, str, str]]:
    """每个工具调用贡献一个指纹,取自该 call 的带参阶段(start/update)。

    ToolExecutionEnd 事件没有 args,其指纹只含工具名,不能用于调用
    比对;必须以 call 首次出现的带参阶段指纹为准。
    """

    fps_by_call: dict[str, str] = {}
    stream: list[tuple[int, str, str]] = []
    for item in evidence:
        if item.tool_call_id is None or item.tool_fingerprint is None:
            continue
        if item.tool_call_id in fps_by_call:
            continue
        fps_by_call[item.tool_call_id] = item.tool_fingerprint
        stream.append((item.sequence, item.tool_call_id, item.tool_fingerprint))
    return stream


def _call_fingerprint_index(
    evidence: Sequence[ProcessEvidence],
) -> dict[str, str]:
    return {
        call_id: fingerprint
        for _sequence, call_id, fingerprint in _call_fingerprint_stream(evidence)
    }


def _first_tool_end_after(
    evidence: Sequence[ProcessEvidence], after: int
) -> ProcessEvidence | None:
    for item in evidence[after + 1 :]:
        if item.tool_phase is ToolPhase.END:
            return item
    return None


def _last_failed_end_before(
    evidence: Sequence[ProcessEvidence], before: int
) -> ProcessEvidence | None:
    for item in reversed(evidence[:before]):
        if item.tool_phase is ToolPhase.END and item.is_error:
            return item
    return None


def _contains_marker(value: str, markers: Sequence[str]) -> bool:
    normalized = value.casefold().replace("-", "_").replace(" ", "_")
    return any(marker in normalized for marker in markers)


__all__ = [
    "ProcessSeverity",
    "ProcessVerification",
    "ProcessVerificationStatus",
    "ProcessVerifier",
    "ProcessViolation",
    "ProcessViolationType",
    "verify_file",
]