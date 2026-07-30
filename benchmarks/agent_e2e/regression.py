"""评测回归门禁、失败轨迹归因与下一版任务集回流。"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Sequence
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from .external_anchor import (
    CalibrationProfileKind,
    CalibrationReport,
)
from .models import (
    EvaluationReport,
    ExperimentManifest,
    FailureMode,
    FailureRecord,
    GateResult,
    GateStatus,
    OfficialScore,
    ReportStatus,
    ResultValidity,
    TaskResult,
    TaskSpec,
    TaskSplit,
    TaskStatus,
    TaskVerdict,
    VersionedModel,
    utc_now,
)
from .trace import TraceEvent


class RegressionGateError(ValueError):
    """回归门禁的输入或可比性不满足不可绕过的评测契约。"""


class FailureFeedbackError(ValueError):
    """失败归因、审查或任务回流违反防泄漏边界。"""


class ChangeKind(str, Enum):
    """必须经过门禁的可配置 Agent 行为变更种类。"""

    PROMPT = "prompt"
    COMPRESSION = "compression"
    TOOL_POLICY = "tool_policy"


class GeneralizationStatus(str, Enum):
    """门禁结论的外部有效性范围。"""

    SELF_ONLY = "self_only"
    EXTERNAL_CALIBRATED = "external_calibrated"


class RegressionGatePolicy(VersionedModel):
    """V1 门禁的非劣边界与三题灾难性回退阈值。"""

    policy_id: str = Field(default="noninferiority-v1", min_length=1, max_length=128)
    max_allowed_drop: float = Field(default=0.10, ge=0, le=1)
    catastrophe_denominator: int = Field(default=3, ge=1)
    extensions: dict[str, Any] = Field(default_factory=dict)


class RegressionGateDecision(VersionedModel):
    """一次候选变更的可复核门禁判定，不保存原始轨迹或提示词。"""

    gate: GateResult
    policy: RegressionGatePolicy
    declared_changes: tuple[ChangeKind, ...] = ()
    baseline_score: OfficialScore | None = None
    candidate_score: OfficialScore | None = None
    delta_success_rate: float | None = Field(default=None, ge=-1, le=1)
    generalization_status: GeneralizationStatus
    comparability_fingerprint: str = Field(min_length=64, max_length=64)
    calibration_report_fingerprint: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
    )
    waiver_reason: str | None = Field(default=None, max_length=320)
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_decision(self) -> RegressionGateDecision:
        comparable_statuses = {GateStatus.PASS, GateStatus.REJECT, GateStatus.WAIVED}
        has_scores = self.baseline_score is not None and self.candidate_score is not None
        if self.gate.status in comparable_statuses and not self.declared_changes:
            raise ValueError("Comparable gate decisions require declared change kinds")
        if self.gate.status in comparable_statuses and not has_scores:
            raise ValueError("Comparable gate decisions require both official scores")
        if self.gate.status is GateStatus.INVALID and (
            self.baseline_score is not None
            or self.candidate_score is not None
            or self.delta_success_rate is not None
        ):
            raise ValueError("Invalid gate decisions cannot carry a score delta")
        if has_scores:
            expected_delta = (
                self.candidate_score.success_rate - self.baseline_score.success_rate
            )
            if self.delta_success_rate is None or not math.isclose(
                self.delta_success_rate,
                expected_delta,
                abs_tol=1e-12,
            ):
                raise ValueError("Gate delta must match the two official scores")
        elif self.delta_success_rate is not None:
            raise ValueError("Gate delta requires both official scores")
        if self.gate.status is GateStatus.WAIVED and not (
            self.waiver_reason and self.waiver_reason.strip()
        ):
            raise ValueError("Waived gate decisions require an explicit waiver reason")
        if (
            self.generalization_status is GeneralizationStatus.EXTERNAL_CALIBRATED
            and self.calibration_report_fingerprint is None
        ):
            raise ValueError("External-calibrated decisions require calibration evidence")
        return self


class GateLedgerEntry(VersionedModel):
    """门禁账本的一条不可变审计记录。"""

    decision: RegressionGateDecision
    merged: bool = False
    merge_reference: str | None = Field(default=None, max_length=160)
    recorded_at: datetime = Field(default_factory=utc_now)
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_merge_reference(self) -> GateLedgerEntry:
        if self.merged and not self.merge_reference:
            raise ValueError("Merged ledger entries require a merge reference")
        if not self.merged and self.merge_reference is not None:
            raise ValueError("Unmerged ledger entries cannot carry a merge reference")
        return self


class RegressionGateLedger(VersionedModel):
    """仅以未合入 reject 计算效果回退的累计拦截次数。"""

    entries: tuple[GateLedgerEntry, ...] = ()
    extensions: dict[str, Any] = Field(default_factory=dict)

    @property
    def intercepted_count(self) -> int:
        """返回被拒绝且未合入候选的累计数。"""

        return sum(
            entry.decision.gate.status is GateStatus.REJECT and not entry.merged
            for entry in self.entries
        )

    def record(
        self,
        decision: RegressionGateDecision,
        *,
        merged: bool = False,
        merge_reference: str | None = None,
    ) -> RegressionGateLedger:
        """追加审计条目并返回新账本，不修改既有证据。"""

        entry = GateLedgerEntry(
            decision=decision,
            merged=merged,
            merge_reference=merge_reference,
        )
        return RegressionGateLedger(
            entries=(*self.entries, entry),
            extensions=self.extensions,
        )


class ReproductionStatus(str, Enum):
    """失败是否能在冻结输入上重现。"""

    REPRODUCED = "reproduced"
    NOT_REPRODUCED = "not_reproduced"
    BLOCKED = "blocked"


class FailureResponsibility(str, Enum):
    """人工审查后记录的责任归属。"""

    AGENT = "agent"
    EVALUATOR = "evaluator"
    INFRASTRUCTURE = "infrastructure"
    UNKNOWN = "unknown"


class FailureTriage(VersionedModel):
    """将规则候选与人工复现、责任判断分离的审查记录。"""

    failure: FailureRecord
    reproduction_status: ReproductionStatus
    responsibility: FailureResponsibility
    review_reason: str = Field(min_length=1, max_length=320)
    reviewer: str = Field(min_length=1, max_length=128)
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_infrastructure_attribution(self) -> FailureTriage:
        if (
            self.failure.primary_mode is FailureMode.INFRASTRUCTURE
            and self.responsibility is FailureResponsibility.AGENT
        ):
            raise ValueError("Infrastructure failures cannot be attributed to the Agent")
        return self


class FeedbackAdmission(VersionedModel):
    """审查通过后写入下一版 catalog 的反馈样本边界。"""

    failure: FailureRecord
    source_task_id: str = Field(min_length=1, max_length=128)
    source_split: TaskSplit
    feedback_task_id: str = Field(min_length=1, max_length=128)
    feedback_split: TaskSplit
    retired_holdout_task_ids: tuple[str, ...] = ()
    active_holdout_task_ids_after_feedback: tuple[str, ...] = ()
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_holdout_retirement(self) -> FeedbackAdmission:
        if self.feedback_split is not TaskSplit.REGRESSION:
            raise ValueError("Feedback tasks must enter the regression split")
        if self.source_task_id == self.feedback_task_id:
            raise ValueError("Feedback task must have a new task ID")
        if len(set(self.retired_holdout_task_ids)) != len(self.retired_holdout_task_ids):
            raise ValueError("Retired holdout IDs must be unique")
        if (
            set(self.retired_holdout_task_ids)
            & set(self.active_holdout_task_ids_after_feedback)
        ):
            raise ValueError("Retired holdout IDs cannot remain active")
        if self.source_split is TaskSplit.HOLDOUT:
            if self.source_task_id not in self.retired_holdout_task_ids:
                raise ValueError("A feedback-derived holdout task must be retired")
            if self.source_task_id in self.active_holdout_task_ids_after_feedback:
                raise ValueError("Feedback-derived holdout cannot remain active")
        return self


_PROFILE_CHANGE_FIELDS = {
    ChangeKind.PROMPT: "prompt_version",
    ChangeKind.COMPRESSION: "compression_version",
    ChangeKind.TOOL_POLICY: "tool_policy_version",
}
_PROFILE_INVARIANT_FIELDS = (
    "model",
    "provider",
    "thinking_level",
    "permission_mode",
    "seed",
    "repeats",
    "timeout_seconds",
    "budget_usd",
    "max_turns",
    "credential_env_vars",
    "extensions",
)
_MANIFEST_INVARIANT_FIELDS = (
    "evaluator_code_sha",
    "task_ids",
    "seed",
    "repeats",
    "timeout_seconds",
    "budget_usd",
    "platform",
    "agent_image_digest",
    "verifier_image_digest",
    "resume_from_run_id",
    "extensions",
)
_FAILURE_PRIORITY = (
    FailureMode.INFRASTRUCTURE,
    FailureMode.LOOP,
    FailureMode.CONTEXT_DECAY,
    FailureMode.TOOL_MISUSE,
    FailureMode.PREMATURE_TERMINATION,
    FailureMode.UNCLASSIFIED,
)
_PREMATURE_MARKERS = (
    "max_turn",
    "turn_limit",
    "max_cost",
    "budget",
    "abort",
    "cancel",
    "timeout",
)


def evaluate_regression_gate(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
    *,
    declared_changes: Iterable[ChangeKind],
    policy: RegressionGatePolicy | None = None,
    waiver_reason: str | None = None,
    calibration: CalibrationReport | None = None,
) -> RegressionGateDecision:
    """比较两次正式运行，仅对同一冻结实验的声明配置差分给出结论。"""

    frozen_policy = policy or RegressionGatePolicy()
    changes = _normalize_changes(declared_changes)
    baseline_run_id = baseline.manifest.run_id
    candidate_run_id = candidate.manifest.run_id
    comparability_fingerprint = _comparability_fingerprint(baseline, candidate)
    errors = _comparability_errors(baseline, candidate, changes)
    if errors:
        return _decision(
            status=GateStatus.INVALID,
            reason=_controlled_reason(errors),
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
            policy=frozen_policy,
            declared_changes=changes,
            comparability_fingerprint=comparability_fingerprint,
            calibration=calibration,
        )

    baseline_score = _official_score_for_gate(baseline)
    candidate_score = _official_score_for_gate(candidate)
    delta = candidate_score.success_rate - baseline_score.success_rate
    generalization = _generalization_status(baseline, candidate, calibration)
    if waiver_reason is not None:
        if not waiver_reason.strip():
            raise RegressionGateError("Waiver reason cannot be blank")
        return _decision(
            status=GateStatus.WAIVED,
            reason="Comparable candidate was explicitly waived",
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
            policy=frozen_policy,
            declared_changes=changes,
            baseline_score=baseline_score,
            candidate_score=candidate_score,
            delta=delta,
            generalization=generalization,
            comparability_fingerprint=comparability_fingerprint,
            calibration=calibration,
            waiver_reason=waiver_reason.strip(),
        )
    if _is_catastrophic_regression(baseline_score, candidate_score, frozen_policy):
        reason = (
            f"Catastrophic regression: {baseline_score.passed_count}/"
            f"{baseline_score.valid_denominator} to {candidate_score.passed_count}/"
            f"{candidate_score.valid_denominator}"
        )
        status = GateStatus.REJECT
    elif delta < -frozen_policy.max_allowed_drop:
        reason = (
            f"Non-inferiority failed: delta {delta:.1%} is below "
            f"-{frozen_policy.max_allowed_drop:.1%}"
        )
        status = GateStatus.REJECT
    else:
        reason = f"Non-inferiority passed: delta {delta:.1%}"
        status = GateStatus.PASS
    return _decision(
        status=status,
        reason=reason,
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        policy=frozen_policy,
        declared_changes=changes,
        baseline_score=baseline_score,
        candidate_score=candidate_score,
        delta=delta,
        generalization=generalization,
        comparability_fingerprint=comparability_fingerprint,
        calibration=calibration,
    )


def write_gate_ledger(
    ledger: RegressionGateLedger,
    *,
    output_path: str | Path,
) -> Path:
    """将严格版本化账本写入调用方指定的审计目录。"""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(ledger.canonical_json() + "\n", encoding="utf-8")
    return path


def load_gate_ledger(path: str | Path) -> RegressionGateLedger:
    """读取严格账本，拒绝 schema 漂移与未知顶层字段。"""

    return RegressionGateLedger.from_json(Path(path).read_text(encoding="utf-8"))


def classify_failure(
    task_result: TaskResult,
    trace_events: Sequence[TraceEvent],
    *,
    allowed_tool_names: Iterable[str] | None,
    reproduction_command: str,
    triage_owner: str | None = None,
) -> FailureRecord:
    """从已脱敏轨迹生成候选失败标签，责任与回流仍由人工审查决定。"""

    if task_result.verdict is TaskVerdict.PASSED:
        raise FailureFeedbackError("A passed task result has no failure to classify")
    if not reproduction_command.strip():
        raise FailureFeedbackError("Failure classification requires a reproduction command")
    events = tuple(sorted(trace_events, key=lambda event: event.sequence))
    _validate_trace_sequences(events)
    mode_offsets: dict[FailureMode, set[int]] = {}
    if _is_infrastructure_result(task_result):
        mode_offsets[FailureMode.INFRASTRUCTURE] = set()
    else:
        loop_offsets = _loop_offsets(events)
        if loop_offsets:
            mode_offsets[FailureMode.LOOP] = loop_offsets
        context_offsets = _context_offsets(events, task_result)
        if context_offsets or _stop_reason_has_context_decay(task_result):
            mode_offsets[FailureMode.CONTEXT_DECAY] = context_offsets
        tool_offsets = _tool_misuse_offsets(events, allowed_tool_names)
        if tool_offsets:
            mode_offsets[FailureMode.TOOL_MISUSE] = tool_offsets
        premature_offsets = _premature_offsets(events, task_result)
        if premature_offsets or _is_premature_stop(task_result):
            mode_offsets[FailureMode.PREMATURE_TERMINATION] = premature_offsets
    modes = tuple(mode for mode in _FAILURE_PRIORITY if mode in mode_offsets)
    if not modes:
        modes = (FailureMode.UNCLASSIFIED,)
        mode_offsets[FailureMode.UNCLASSIFIED] = set()
    evidence_offsets = tuple(
        sorted({offset for offsets in mode_offsets.values() for offset in offsets})
    )
    primary_mode = modes[0]
    secondary_modes = modes[1:]
    return FailureRecord(
        task_id=task_result.task_id,
        attempt=task_result.attempt,
        primary_mode=primary_mode,
        secondary_modes=secondary_modes,
        evidence_offsets=evidence_offsets,
        failure_signature=_failure_signature(
            primary_mode=primary_mode,
            secondary_modes=secondary_modes,
            events=events,
            evidence_offsets=evidence_offsets,
            task_result=task_result,
        ),
        reproduction_command=reproduction_command.strip(),
        triage_owner=triage_owner,
        extensions={
            "classifier_version": "failure-rules-v1",
            "mode_offsets": {
                mode.value: tuple(sorted(offsets))
                for mode, offsets in mode_offsets.items()
            },
        },
    )


def deduplicate_failure_records(
    records: Iterable[FailureRecord],
) -> tuple[FailureRecord, ...]:
    """按脱敏失败签名标注后续重复项，保留第一条供人工审查。"""

    seen_signatures: set[str] = set()
    deduplicated: list[FailureRecord] = []
    for record in records:
        is_duplicate = record.deduplicated or record.failure_signature in seen_signatures
        deduplicated.append(record.model_copy(update={"deduplicated": is_duplicate}))
        seen_signatures.add(record.failure_signature)
    return tuple(deduplicated)


def admit_failure_to_regression(
    triage: FailureTriage,
    *,
    source_task: TaskSpec,
    feedback_task: TaskSpec,
    active_holdout_task_ids: Iterable[str],
    retired_holdout_task_ids: Iterable[str],
) -> FeedbackAdmission:
    """将已复现且归因给 Agent 的失败加入下一版 regression catalog。"""

    failure = triage.failure
    if failure.task_id != source_task.task_id:
        raise FailureFeedbackError("Triage failure must match the source task")
    if triage.reproduction_status is not ReproductionStatus.REPRODUCED:
        raise FailureFeedbackError("Only reproduced failures can enter regression")
    if triage.responsibility is not FailureResponsibility.AGENT:
        raise FailureFeedbackError("Only Agent-attributed failures can enter regression")
    if failure.deduplicated:
        raise FailureFeedbackError("Deduplicated failures cannot create another regression task")
    if feedback_task.split is not TaskSplit.REGRESSION:
        raise FailureFeedbackError("Feedback task must use the regression split")
    if feedback_task.status is not TaskStatus.ACTIVE:
        raise FailureFeedbackError("Feedback task must be active in the next catalog")
    if feedback_task.task_id == source_task.task_id:
        raise FailureFeedbackError("Feedback task ID must differ from the source task")

    active_holdouts = _unique_ids(active_holdout_task_ids, label="Active holdout")
    retired_holdouts = _unique_ids(retired_holdout_task_ids, label="Retired holdout")
    if source_task.split is TaskSplit.HOLDOUT:
        if source_task.task_id not in active_holdouts:
            raise FailureFeedbackError("Source holdout must be active before feedback")
        if source_task.task_id not in retired_holdouts:
            raise FailureFeedbackError("Source holdout must be retired before feedback")
        holdout_reason = (
            f"Failure admitted as regression task {feedback_task.task_id}; "
            "source holdout retired"
        )
    else:
        holdout_reason = None
    active_after = tuple(task_id for task_id in active_holdouts if task_id not in retired_holdouts)
    admitted_failure = failure.model_copy(
        update={
            "feedback_split": TaskSplit.REGRESSION,
            "holdout_exclusion_reason": holdout_reason,
        }
    )
    return FeedbackAdmission(
        failure=admitted_failure,
        source_task_id=source_task.task_id,
        source_split=source_task.split,
        feedback_task_id=feedback_task.task_id,
        feedback_split=feedback_task.split,
        retired_holdout_task_ids=retired_holdouts,
        active_holdout_task_ids_after_feedback=active_after,
        extensions={"triage_fingerprint": triage.fingerprint()},
    )


def _decision(
    *,
    status: GateStatus,
    reason: str,
    baseline_run_id: str,
    candidate_run_id: str,
    policy: RegressionGatePolicy,
    declared_changes: tuple[ChangeKind, ...],
    comparability_fingerprint: str,
    calibration: CalibrationReport | None,
    baseline_score: OfficialScore | None = None,
    candidate_score: OfficialScore | None = None,
    delta: float | None = None,
    generalization: GeneralizationStatus = GeneralizationStatus.SELF_ONLY,
    waiver_reason: str | None = None,
) -> RegressionGateDecision:
    return RegressionGateDecision(
        gate=GateResult(
            status=status,
            reason=reason,
            baseline_run_id=baseline_run_id,
            candidate_run_id=candidate_run_id,
        ),
        policy=policy,
        declared_changes=declared_changes,
        baseline_score=baseline_score,
        candidate_score=candidate_score,
        delta_success_rate=delta,
        generalization_status=generalization,
        comparability_fingerprint=comparability_fingerprint,
        calibration_report_fingerprint=(calibration.fingerprint() if calibration else None),
        waiver_reason=waiver_reason,
    )


def _normalize_changes(changes: Iterable[ChangeKind]) -> tuple[ChangeKind, ...]:
    normalized = {ChangeKind(change) for change in changes}
    return tuple(sorted(normalized, key=lambda change: change.value))


def _comparability_errors(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
    declared_changes: tuple[ChangeKind, ...],
) -> list[str]:
    errors: list[str] = []
    if not declared_changes:
        errors.append("At least one prompt, compression, or tool change must be declared")
    baseline_manifest = baseline.manifest
    candidate_manifest = candidate.manifest
    if baseline_manifest.run_id == candidate_manifest.run_id:
        errors.append("Baseline and candidate must use distinct run IDs")
    _compare_catalog_locks(baseline_manifest, candidate_manifest, errors)
    for field_name in _MANIFEST_INVARIANT_FIELDS:
        if getattr(baseline_manifest, field_name) != getattr(candidate_manifest, field_name):
            errors.append(f"Manifest field differs: {field_name}")
    baseline_profile = baseline_manifest.profile
    candidate_profile = candidate_manifest.profile
    for field_name in _PROFILE_INVARIANT_FIELDS:
        if getattr(baseline_profile, field_name) != getattr(candidate_profile, field_name):
            errors.append(f"Profile field differs: {field_name}")
    actual_changes = {
        change
        for change, field_name in _PROFILE_CHANGE_FIELDS.items()
        if getattr(baseline_profile, field_name) != getattr(candidate_profile, field_name)
    }
    if actual_changes != set(declared_changes):
        errors.append("Declared change kinds do not match profile version differences")
    if not actual_changes:
        errors.append("Candidate does not change a gate-controlled profile version")
    try:
        _official_score_for_gate(baseline)
        _official_score_for_gate(candidate)
    except RegressionGateError as error:
        errors.append(str(error))
    return errors


def _compare_catalog_locks(
    baseline: ExperimentManifest,
    candidate: ExperimentManifest,
    errors: list[str],
) -> None:
    baseline_lock = baseline.catalog
    candidate_lock = candidate.catalog
    for field_name in (
        "catalog_id",
        "catalog_version",
        "catalog_sha256",
        "task_ids",
        "extensions",
    ):
        if getattr(baseline_lock, field_name) != getattr(candidate_lock, field_name):
            errors.append(f"Catalog lock field differs: {field_name}")


def _official_score_for_gate(report: EvaluationReport) -> OfficialScore:
    if report.status is not ReportStatus.OFFICIAL or report.official_score is None:
        raise RegressionGateError("Gate requires a complete official report")
    expected_pairs = {
        (task_id, attempt)
        for task_id in report.manifest.task_ids
        for attempt in range(1, report.manifest.repeats + 1)
    }
    actual_pairs = {(result.task_id, result.attempt) for result in report.results}
    if len(report.results) != len(expected_pairs) or actual_pairs != expected_pairs:
        raise RegressionGateError("Official report must cover every frozen task and repeat")
    if any(
        not result.official
        or result.validity is not ResultValidity.VALID
        or result.verdict not in {TaskVerdict.PASSED, TaskVerdict.FAILED}
        for result in report.results
    ):
        raise RegressionGateError("Gate requires only valid official task results")
    expected_denominator = len(expected_pairs)
    if report.official_score.valid_denominator != expected_denominator:
        raise RegressionGateError("Official denominator does not cover the frozen task set")
    return report.official_score


def _is_catastrophic_regression(
    baseline: OfficialScore,
    candidate: OfficialScore,
    policy: RegressionGatePolicy,
) -> bool:
    return (
        baseline.valid_denominator == policy.catastrophe_denominator
        and candidate.valid_denominator == policy.catastrophe_denominator
        and baseline.passed_count == policy.catastrophe_denominator
        and candidate.passed_count == 0
    )


def _generalization_status(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
    calibration: CalibrationReport | None,
) -> GeneralizationStatus:
    if calibration is None or not _has_accepted_calibration(calibration):
        return GeneralizationStatus.SELF_ONLY
    fingerprints = {point.profile_fingerprint for point in calibration.points}
    if {
        baseline.manifest.profile_fingerprint,
        candidate.manifest.profile_fingerprint,
    }.issubset(fingerprints):
        return GeneralizationStatus.EXTERNAL_CALIBRATED
    return GeneralizationStatus.SELF_ONLY


def _has_accepted_calibration(calibration: CalibrationReport) -> bool:
    unique_profiles = {point.profile_fingerprint for point in calibration.points}
    profile_kinds = {point.profile_kind for point in calibration.points}
    candidate_count = sum(
        point.profile_kind is CalibrationProfileKind.CANDIDATE
        for point in calibration.points
    )
    return (
        calibration.accepted
        and len(unique_profiles) >= 5
        and CalibrationProfileKind.BASELINE in profile_kinds
        and CalibrationProfileKind.DEGRADED in profile_kinds
        and candidate_count >= 3
        and calibration.spearman_rho is not None
        and calibration.spearman_rho >= 0.70
        and calibration.direction_pairs > 0
        and calibration.direction_agreement is not None
        and calibration.direction_agreement >= 0.80
    )


def _comparability_fingerprint(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
) -> str:
    return _digest(
        {
            "baseline": _manifest_comparability_snapshot(baseline.manifest),
            "candidate": _manifest_comparability_snapshot(candidate.manifest),
        }
    )


def _manifest_comparability_snapshot(manifest: ExperimentManifest) -> dict[str, Any]:
    profile = manifest.profile
    return {
        "catalog": {
            "catalog_id": manifest.catalog.catalog_id,
            "catalog_version": manifest.catalog.catalog_version,
            "catalog_sha256": manifest.catalog.catalog_sha256,
            "task_ids": manifest.catalog.task_ids,
            "extensions": manifest.catalog.extensions,
        },
        "manifest": {
            field_name: getattr(manifest, field_name)
            for field_name in _MANIFEST_INVARIANT_FIELDS
        },
        "profile": {
            field_name: getattr(profile, field_name)
            for field_name in (*_PROFILE_INVARIANT_FIELDS, *_PROFILE_CHANGE_FIELDS.values())
        },
    }


def _controlled_reason(parts: Sequence[str]) -> str:
    reason = "; ".join(parts)
    return reason[:320]


def _validate_trace_sequences(events: Sequence[TraceEvent]) -> None:
    sequences = [event.sequence for event in events]
    if len(set(sequences)) != len(sequences):
        raise FailureFeedbackError("Trace event sequences must be unique")


def _is_infrastructure_result(task_result: TaskResult) -> bool:
    return task_result.verdict in {
        TaskVerdict.BLOCKED,
        TaskVerdict.INVALID,
    } or task_result.validity in {
        ResultValidity.BLOCKED,
        ResultValidity.INVALID,
        ResultValidity.OFFLINE_ONLY,
    }


def _loop_offsets(events: Sequence[TraceEvent]) -> set[int]:
    offsets: set[int] = set()
    for first, second, third in zip(events, events[1:], events[2:], strict=False):
        if (
            second.sequence != first.sequence + 1
            or third.sequence != second.sequence + 1
        ):
            continue
        fingerprint = _tool_call_fingerprint(first)
        if fingerprint is None:
            continue
        if fingerprint == _tool_call_fingerprint(second) == _tool_call_fingerprint(third):
            offsets.update((first.sequence, second.sequence, third.sequence))
    return offsets


def _tool_call_fingerprint(event: TraceEvent) -> tuple[str, str, str | None] | None:
    if event.tool_name is None or event.argument_digest is None:
        return None
    return event.tool_name, event.argument_digest, event.workspace_fingerprint


def _context_offsets(events: Sequence[TraceEvent], task_result: TaskResult) -> set[int]:
    del task_result
    return {
        event.sequence
        for event in events
        if _contains_marker(event.event_type, ("context", "compact"))
    }


def _stop_reason_has_context_decay(task_result: TaskResult) -> bool:
    return bool(
        task_result.agent_run
        and _contains_marker(task_result.agent_run.stop_reason, ("context", "compact"))
    )


def _tool_misuse_offsets(
    events: Sequence[TraceEvent],
    allowed_tool_names: Iterable[str] | None,
) -> set[int]:
    allowed = None if allowed_tool_names is None else frozenset(allowed_tool_names)
    offsets: set[int] = set()
    for event in events:
        disallowed_tool = allowed is not None and (
            event.tool_name is not None and event.tool_name not in allowed
        )
        tool_error = _contains_marker(
            event.event_type,
            ("tool_error", "toolerror", "permission", "denied", "unauthorized"),
        )
        if disallowed_tool or tool_error:
            offsets.add(event.sequence)
    return offsets


def _premature_offsets(events: Sequence[TraceEvent], task_result: TaskResult) -> set[int]:
    del task_result
    return {
        event.sequence
        for event in events
        if _contains_marker(event.event_type, _PREMATURE_MARKERS)
    }


def _is_premature_stop(task_result: TaskResult) -> bool:
    return bool(
        task_result.agent_run
        and _contains_marker(task_result.agent_run.stop_reason, _PREMATURE_MARKERS)
    )


def _contains_marker(value: str, markers: Sequence[str]) -> bool:
    normalized = value.casefold().replace("-", "_").replace(" ", "_")
    return any(marker in normalized for marker in markers)


def _failure_signature(
    *,
    primary_mode: FailureMode,
    secondary_modes: tuple[FailureMode, ...],
    events: Sequence[TraceEvent],
    evidence_offsets: tuple[int, ...],
    task_result: TaskResult,
) -> str:
    event_by_offset = {event.sequence: event for event in events}
    signals = [
        {
            "event_type": event_by_offset[offset].event_type.casefold(),
            "tool_name": event_by_offset[offset].tool_name,
            "argument_digest": event_by_offset[offset].argument_digest,
            "workspace_fingerprint": event_by_offset[offset].workspace_fingerprint,
        }
        for offset in evidence_offsets
    ]
    return _digest(
        {
            "primary_mode": primary_mode.value,
            "secondary_modes": tuple(mode.value for mode in secondary_modes),
            "signals": signals,
            "stop_reason": (
                task_result.agent_run.stop_reason.casefold()
                if task_result.agent_run is not None
                else None
            ),
            "validity": task_result.validity.value,
            "verdict": task_result.verdict.value,
        }
    )


def _unique_ids(values: Iterable[str], *, label: str) -> tuple[str, ...]:
    ids = tuple(values)
    if any(not task_id.strip() for task_id in ids):
        raise FailureFeedbackError(f"{label} IDs cannot be blank")
    if len(set(ids)) != len(ids):
        raise FailureFeedbackError(f"{label} IDs must be unique")
    return ids


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
