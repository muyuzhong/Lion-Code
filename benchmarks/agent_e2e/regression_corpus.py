"""Harness Regression Corpus:从 FirstErrorAttribution 沉淀最小 RegressionCase,
并提供确定性的离线重放 runner。

corpus 保存结构化 ``ProcessEvidence``(最小失败片段)+ 溯源字段,绝不保存
#149 的可读字符串 snippet——字符串只给人看,不能作为稳定机器回放协议。
只有高置信(confidence == 1.0)、且 candidate 证据上有确定性
``ProcessViolation`` 的 attribution 才允许自动沉淀;低置信(PASS→FAIL
行为分歧 0.6)、证据不可用、纯行为分歧(TOOL_SELECTION / TOOL_ARGUMENT /
UNKNOWN)一律不进入 corpus。V1 不做自动修改 Harness、不生成补丁、无 LLM
judge、不重跑模型。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from enum import Enum

from pydantic import Field, model_validator

from .evidence import ProcessEvidence
from .first_error import FirstErrorAttribution, FirstErrorKind
from .models import TaskResult, TaskSpec, VersionedModel
from .process_verifier import (
    ProcessReplayContext,
    ProcessVerification,
    ProcessVerificationStatus,
    ProcessVerifier,
    ProcessViolation,
    ProcessViolationType,
)
from .regression_probe import minimize_failure_evidence

# V1 允许自动沉淀的确定性 violation;TOOL_SELECTION / TOOL_ARGUMENT /
# UNKNOWN(纯分歧)不在此列。
_SUPPORTED_VIOLATIONS: frozenset[ProcessViolationType] = frozenset(
    {
        ProcessViolationType.TEST_TAMPERING,
        ProcessViolationType.TOOL_ERROR_NOT_RECOVERED,
        ProcessViolationType.VALIDATION_MISSING,
        ProcessViolationType.CONTEXT_REGRESSION,
        ProcessViolationType.PREMATURE_TERMINATION,
        ProcessViolationType.REPEATED_TOOL_CALL,
    }
)

# FirstErrorKind → 确定性 violation;REPEATED_TOOL_CALL 在 first_error 中
# 映射为 FirstErrorKind.UNKNOWN(有歧义),依赖实际 violation 匹配而不是
# kind 白名单。
_KIND_TO_VIOLATION: dict[FirstErrorKind, ProcessViolationType] = {
    FirstErrorKind.PROCESS_VIOLATION: ProcessViolationType.TEST_TAMPERING,
    FirstErrorKind.ERROR_RECOVERY: ProcessViolationType.TOOL_ERROR_NOT_RECOVERED,
    FirstErrorKind.VALIDATION: ProcessViolationType.VALIDATION_MISSING,
    FirstErrorKind.CONTEXT: ProcessViolationType.CONTEXT_REGRESSION,
    FirstErrorKind.TERMINATION: ProcessViolationType.PREMATURE_TERMINATION,
}

_VIOLATION_PRIORITY: dict[ProcessViolationType, int] = {
    ProcessViolationType.TEST_TAMPERING: 0,
    ProcessViolationType.TOOL_ERROR_NOT_RECOVERED: 1,
    ProcessViolationType.VALIDATION_MISSING: 2,
    ProcessViolationType.CONTEXT_REGRESSION: 3,
    ProcessViolationType.PREMATURE_TERMINATION: 4,
    ProcessViolationType.REPEATED_TOOL_CALL: 5,
}


class RegressionCase(VersionedModel):
    """一条最小、自包含、可离线重放的回归用例。

    ``evidence`` 是结构化 ``ProcessEvidence`` 最小失败片段;
    ``replay_context`` 携带 verifier 消费的极简字段,重放不依赖原始
    TaskSpec/TaskResult 对象。
    """

    case_id: str = Field(min_length=1, max_length=200)
    source_task_id: str = Field(min_length=1, max_length=128)
    source_attempt: int = Field(ge=1)
    source_run_id: str | None = Field(default=None, max_length=200)
    first_error_kind: FirstErrorKind
    expected_violation: ProcessViolationType
    expected_status: ProcessVerificationStatus
    evidence: tuple[ProcessEvidence, ...]
    source_fingerprint: str = Field(min_length=64, max_length=64)
    original_evidence_count: int = Field(ge=0)
    minimized_evidence_count: int = Field(ge=1)
    replay_context: ProcessReplayContext = Field(default_factory=ProcessReplayContext)

    @model_validator(mode="after")
    def _validate_counts(self) -> RegressionCase:
        if self.minimized_evidence_count != len(self.evidence):
            raise ValueError("minimized_evidence_count must equal evidence length")
        if self.original_evidence_count < self.minimized_evidence_count:
            raise ValueError(
                "original_evidence_count cannot be smaller than minimized_evidence_count"
            )
        return self


class RegressionCaseStatus(str, Enum):
    """单条 case 的离线重放判定。"""

    PASS = "pass"
    FAIL = "fail"
    INVALID = "invalid"


class RegressionCaseResult(VersionedModel):
    """单条 case 的重放结果:期望与实际 violation/status 对比。"""

    case_id: str = Field(min_length=1, max_length=200)
    status: RegressionCaseStatus
    passed: bool
    expected_violation: ProcessViolationType | None
    actual_violations: tuple[ProcessViolationType, ...]
    expected_status: ProcessVerificationStatus
    actual_status: ProcessVerificationStatus
    reason: str = Field(min_length=1, max_length=320)

    @model_validator(mode="after")
    def _validate_passed(self) -> RegressionCaseResult:
        if self.passed != (self.status is RegressionCaseStatus.PASS):
            raise ValueError("passed must be True only for PASS status")
        return self


class RegressionCorpusReport(VersionedModel):
    """整个 corpus 的离线重放聚合报告。"""

    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    invalid: int = Field(ge=0)
    results: tuple[RegressionCaseResult, ...] = ()

    @model_validator(mode="after")
    def _validate_counts(self) -> RegressionCorpusReport:
        if self.total != len(self.results):
            raise ValueError("total must equal results length")
        counts = {
            RegressionCaseStatus.PASS: self.passed,
            RegressionCaseStatus.FAIL: self.failed,
            RegressionCaseStatus.INVALID: self.invalid,
        }
        if sum(counts.values()) != self.total:
            raise ValueError("status counts must sum to total")
        for result in self.results:
            counts[result.status] -= 1
        if any(value != 0 for value in counts.values()):
            raise ValueError("status counts must match per-result statuses")
        return self


def attribution_can_enter_corpus(
    attribution: FirstErrorAttribution,
    *,
    task: TaskSpec,
    candidate_result: TaskResult,
    candidate_evidence: Sequence[ProcessEvidence],
    verifier: ProcessVerifier | None = None,
) -> tuple[bool, str]:
    """attribution 是否够格自动沉淀为 RegressionCase。

    三条硬门槛:证据可用、confidence == 1.0、candidate 证据上存在受
    支持的确定性 violation。以实际 violation 为准而不是 kind 白名单,
    否则 REPEATED_TOOL_CALL(kind=UNKNOWN)会被误拒。
    """

    if not attribution.evidence_available:
        return False, "过程证据不可用(旧格式/空轨迹),无法归因"
    if attribution.confidence < 1.0:
        return (
            False,
            f"低置信 attribution(confidence={attribution.confidence}),不自动沉淀",
        )
    active = verifier or ProcessVerifier()
    verification = active.verify(
        task=task,
        task_result=candidate_result,
        trace_events=(),
        evidence=candidate_evidence,
    )
    present = {violation.violation_type for violation in verification.violations}
    if not (present & _SUPPORTED_VIOLATIONS):
        return False, "candidate 证据上无可映射到确定性 violation 的信号"
    return True, ""


def regression_case_from_attribution(
    *,
    task: TaskSpec,
    candidate_result: TaskResult,
    candidate_evidence: Sequence[ProcessEvidence],
    attribution: FirstErrorAttribution,
    source_run_id: str | None = None,
    case_id: str | None = None,
    verifier: ProcessVerifier | None = None,
) -> RegressionCase | None:
    """把高置信、有确定性 violation 的 attribution 沉淀为最小 RegressionCase。

    任一入库条件不满足时返回 None;成功后对 candidate evidence 做失败
    片段最小化,并把最小片段 + 溯源 + 重放上下文一起打包。
    """

    accepted, _reason = attribution_can_enter_corpus(
        attribution,
        task=task,
        candidate_result=candidate_result,
        candidate_evidence=candidate_evidence,
        verifier=verifier,
    )
    if not accepted:
        return None
    active = verifier or ProcessVerifier()
    verification = active.verify(
        task=task,
        task_result=candidate_result,
        trace_events=(),
        evidence=candidate_evidence,
    )
    supported = [
        violation
        for violation in verification.violations
        if violation.violation_type in _SUPPORTED_VIOLATIONS
    ]
    target = _pick_target_violation(attribution, verification, supported)
    minimized = minimize_failure_evidence(
        violation_type=target,
        task=task,
        task_result=candidate_result,
        evidence=candidate_evidence,
        verifier=active,
    )
    replay_verification = active.verify(
        task=task,
        task_result=candidate_result,
        trace_events=(),
        evidence=minimized,
    )
    resolved_id = case_id or _default_case_id(
        task.task_id, candidate_result.attempt, attribution.fingerprint()
    )
    return RegressionCase(
        case_id=resolved_id,
        source_task_id=task.task_id,
        source_attempt=candidate_result.attempt,
        source_run_id=source_run_id,
        first_error_kind=attribution.kind,
        expected_violation=target,
        expected_status=replay_verification.status,
        evidence=minimized,
        source_fingerprint=_source_fingerprint(attribution, candidate_evidence),
        original_evidence_count=len(candidate_evidence),
        minimized_evidence_count=len(minimized),
        replay_context=ProcessReplayContext(
            verdict=candidate_result.verdict,
            stop_reason=(
                candidate_result.agent_run.stop_reason
                if candidate_result.agent_run is not None
                else None
            ),
            public_validation_commands=task.public_validation_commands,
        ),
    )


def run_regression_corpus(
    cases: Sequence[RegressionCase],
    *,
    verifier: ProcessVerifier | None = None,
) -> RegressionCorpusReport:
    """对 corpus 逐条离线重放:同输入必得同报告(确定性)。

    每条 case 用自带 ``replay_context`` 跑 ``verify_case``,比较实际
    violation/status 与 expected,输出 PASS / FAIL / INVALID。
    """

    active = verifier or ProcessVerifier()
    results = tuple(_replay_case(case, active) for case in cases)
    return RegressionCorpusReport(
        total=len(results),
        passed=sum(result.status is RegressionCaseStatus.PASS for result in results),
        failed=sum(result.status is RegressionCaseStatus.FAIL for result in results),
        invalid=sum(
            result.status is RegressionCaseStatus.INVALID for result in results
        ),
        results=results,
    )


def _pick_target_violation(
    attribution: FirstErrorAttribution,
    verification: ProcessVerification,
    supported: Sequence[ProcessViolation],
) -> ProcessViolationType:
    """选这条 case 要钉住的 violation:优先与 attribution.kind 一致。

    kind=UNKNOWN(REPEATED_TOOL_CALL 在 first_error 中的映射)或与 kind
    不一致时,取优先级最高(最早)的受支持 violation,保证可复现。
    """

    expected = _KIND_TO_VIOLATION.get(attribution.kind)
    for violation in supported:
        if violation.violation_type is expected:
            return violation.violation_type
    return min(
        supported,
        key=lambda violation: (
            _VIOLATION_PRIORITY.get(violation.violation_type, 99),
            violation.evidence_offsets[0] if violation.evidence_offsets else 0,
        ),
    ).violation_type


def _replay_case(
    case: RegressionCase, verifier: ProcessVerifier
) -> RegressionCaseResult:
    verification = verifier.verify_case(
        evidence=case.evidence,
        context=case.replay_context,
        task_id=case.source_task_id,
    )
    if case.expected_status is ProcessVerificationStatus.EVIDENCE_UNAVAILABLE:
        return RegressionCaseResult(
            case_id=case.case_id,
            status=RegressionCaseStatus.INVALID,
            passed=False,
            expected_violation=case.expected_violation,
            actual_violations=(),
            expected_status=case.expected_status,
            actual_status=verification.status,
            reason="case 未记录可比较的 expected status,无法重放",
        )
    if verification.status is ProcessVerificationStatus.EVIDENCE_UNAVAILABLE:
        return RegressionCaseResult(
            case_id=case.case_id,
            status=RegressionCaseStatus.INVALID,
            passed=False,
            expected_violation=case.expected_violation,
            actual_violations=(),
            expected_status=case.expected_status,
            actual_status=verification.status,
            reason="证据不可用(空 evidence),无法离线重放",
        )
    actual_violations = tuple(
        violation.violation_type for violation in verification.violations
    )
    expected_holds = case.expected_violation in actual_violations
    status_holds = verification.status is case.expected_status
    if expected_holds and status_holds:
        return RegressionCaseResult(
            case_id=case.case_id,
            status=RegressionCaseStatus.PASS,
            passed=True,
            expected_violation=case.expected_violation,
            actual_violations=actual_violations,
            expected_status=case.expected_status,
            actual_status=verification.status,
            reason="expected violation 与 expected status 均复现",
        )
    return RegressionCaseResult(
        case_id=case.case_id,
        status=RegressionCaseStatus.FAIL,
        passed=False,
        expected_violation=case.expected_violation,
        actual_violations=actual_violations,
        expected_status=case.expected_status,
        actual_status=verification.status,
        reason="expected violation 或 expected status 未复现(Harness 行为已变化)",
    )


def _source_fingerprint(
    attribution: FirstErrorAttribution,
    evidence: Sequence[ProcessEvidence],
) -> str:
    """来源指纹:attribution + 原始证据的稳定摘要,用于坏 case 溯源与去重。"""

    payload = {
        "attribution": json.loads(attribution.canonical_json()),
        "evidence": [
            json.loads(item.canonical_json())
            for item in sorted(evidence, key=lambda item: item.sequence)
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _default_case_id(task_id: str, attempt: int, attribution_fingerprint: str) -> str:
    return f"{task_id}:a{attempt}:{attribution_fingerprint[:12]}"


__all__ = [
    "RegressionCase",
    "RegressionCaseResult",
    "RegressionCaseStatus",
    "RegressionCorpusReport",
    "attribution_can_enter_corpus",
    "regression_case_from_attribution",
    "run_regression_corpus",
]
