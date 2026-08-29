"""配对实验层: Harness Variant 与逐题配对实验。

中心问题从「这个版本的 Agent 得了多少分」改为「仅切换一个 Harness
变量时,同一冻结任务上哪些任务 fail→pass / pass→fail」。本模块只做
实验对象与配对契约,复用现有 EvaluationReport / TaskResult,不触碰
执行链与官方 verifier 判定。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from .models import (
    EvaluationReport,
    ExperimentProfile,
    ReportStatus,
    ResultValidity,
    TaskResult,
    TaskVerdict,
    VersionedModel,
)
from .regression import ChangeKind

# 与 regression.py 门禁契约保持一致的可比字段清单(不导入其私有常量)。
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
_PROFILE_CHANGE_FIELDS = {
    ChangeKind.PROMPT: "prompt_version",
    ChangeKind.COMPRESSION: "compression_version",
    ChangeKind.TOOL_POLICY: "tool_policy_version",
}
_CATALOG_LOCK_FIELDS = (
    "catalog_id",
    "catalog_version",
    "catalog_sha256",
    "task_ids",
    "extensions",
)


class PairedExperimentError(ValueError):
    """配对实验的可比性或契约校验失败。"""


class PairedTrialOutcome(str, Enum):
    """单题配对的结果迁移方向(四格 + 不可比)。"""

    FAIL_TO_PASS = "fail_to_pass"
    PASS_TO_FAIL = "pass_to_fail"
    PASS_TO_PASS = "pass_to_pass"
    FAIL_TO_FAIL = "fail_to_fail"
    INVALID = "invalid"


class ExperimentKind(str, Enum):
    """配对实验的因果语义。

    - ``CONTROLLED``:两侧 agent_code_sha 相同,差异仅限声明的
      Harness 变量(经 worker 注入)→ 可以谈「该机制导致的变化」;
    - ``REGRESSION``:Harness 代码版本不同 → 只能谈「版本整体是否
      回归」,不能归因到具体机制。
    """

    CONTROLLED = "controlled"
    REGRESSION = "regression"


class HarnessVariant(VersionedModel):
    """一次实验中 Harness 的可变部分,作为评估的一等公民。

    只承载可独立开关的 Harness 变量(prompt / compression /
    tool_policy);model、provider、seed、budget 等不变量不属于
    variant 的可变面,由 ``from_profile`` 的显式字段清单保证。
    """

    variant_id: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=128)
    compression_version: str = Field(min_length=1, max_length=128)
    tool_policy_version: str = Field(min_length=1, max_length=128)
    extensions: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_profile(
        cls,
        profile: ExperimentProfile,
        *,
        variant_id: str,
    ) -> HarnessVariant:
        """从现有 ``ExperimentProfile`` 提取可变字段生成 variant。"""

        return cls(
            variant_id=variant_id,
            prompt_version=profile.prompt_version,
            compression_version=profile.compression_version,
            tool_policy_version=profile.tool_policy_version,
        )

    def change_kinds(self, other: HarnessVariant) -> tuple[ChangeKind, ...]:
        """返回本方相对另一 variant 实际不同的 ``ChangeKind`` 集合。"""

        changed = {
            kind
            for kind, field_name in _PROFILE_CHANGE_FIELDS.items()
            if getattr(self, field_name) != getattr(other, field_name)
        }
        return tuple(sorted(changed, key=lambda kind: kind.value))


class PairedTrial(VersionedModel):
    """同一 task × attempt 上 baseline 与 candidate 的单题配对。"""

    task_id: str = Field(min_length=1, max_length=128)
    attempt: int = Field(ge=1)
    baseline_result: TaskResult
    candidate_result: TaskResult
    outcome_delta: PairedTrialOutcome
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_trial_pair(self) -> PairedTrial:
        baseline_key = (self.baseline_result.task_id, self.baseline_result.attempt)
        candidate_key = (self.candidate_result.task_id, self.candidate_result.attempt)
        if baseline_key != (self.task_id, self.attempt):
            raise ValueError("Baseline result does not match the trial key")
        if candidate_key != (self.task_id, self.attempt):
            raise ValueError("Candidate result does not match the trial key")
        comparable = _is_comparable_result(self.baseline_result) and _is_comparable_result(
            self.candidate_result
        )
        if comparable and self.outcome_delta is PairedTrialOutcome.INVALID:
            raise ValueError("Comparable trial pair cannot carry INVALID delta")
        if not comparable and self.outcome_delta is not PairedTrialOutcome.INVALID:
            raise ValueError("Incomparable trial pair requires INVALID delta")
        return self


class PairedCounts(VersionedModel):
    """配对四格计数;不在此层做统计显著性。"""

    fail_to_pass: int = Field(ge=0)
    pass_to_fail: int = Field(ge=0)
    pass_to_pass: int = Field(ge=0)
    fail_to_fail: int = Field(ge=0)
    invalid: int = Field(ge=0)


class PairedExperimentReport(VersionedModel):
    """一次配对实验的可复核报告:逐题明细 + 四格计数 + 可比性指纹。

    报告不包含统计检验结论(属于配对统计/Gate V2 层)与原始轨迹。
    """

    baseline_run_id: str = Field(min_length=1, max_length=128)
    candidate_run_id: str = Field(min_length=1, max_length=128)
    experiment_kind: ExperimentKind
    baseline_agent_code_sha: str = Field(min_length=7, max_length=128)
    candidate_agent_code_sha: str = Field(min_length=7, max_length=128)
    injection_fingerprint: str | None = Field(
        default=None, min_length=64, max_length=64
    )
    declared_changes: tuple[ChangeKind, ...] = Field(min_length=1)
    comparability_fingerprint: str = Field(min_length=64, max_length=64)
    trials: tuple[PairedTrial, ...] = ()
    counts: PairedCounts
    extensions: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_counts(self) -> PairedExperimentReport:
        expected = _count_trials(self.trials)
        if (
            self.counts.fail_to_pass != expected.fail_to_pass
            or self.counts.pass_to_fail != expected.pass_to_fail
            or self.counts.pass_to_pass != expected.pass_to_pass
            or self.counts.fail_to_fail != expected.fail_to_fail
            or self.counts.invalid != expected.invalid
        ):
            raise ValueError("Report counts do not match its trials")
        return self

    @model_validator(mode="after")
    def _validate_experiment_kind(self) -> PairedExperimentReport:
        same_code = (
            self.baseline_agent_code_sha == self.candidate_agent_code_sha
        )
        if self.experiment_kind is ExperimentKind.CONTROLLED and not same_code:
            raise ValueError("Controlled experiments require identical agent code")
        if self.experiment_kind is ExperimentKind.REGRESSION and same_code:
            raise ValueError("Regression comparisons require different agent code")
        return self

    def render_markdown(self) -> str:
        """生成中文四格摘要报告,按实验语义区分结论措辞。"""

        changes = ", ".join(kind.value for kind in self.declared_changes)
        if self.experiment_kind is ExperimentKind.CONTROLLED:
            conclusion = (
                "受控实验(两侧 agent 代码相同):配对差异可归因于声明"
                f"变更 [{changes}] 的机制效果。"
            )
        else:
            conclusion = (
                "跨版本回归比较(agent 代码不同):配对差异只说明版本"
                "整体回归,不可归因到具体机制。"
            )
        lines = [
            "# 配对实验报告",
            "",
            f"- baseline: `{self.baseline_run_id}` (agent {self.baseline_agent_code_sha})",
            f"- candidate: `{self.candidate_run_id}` (agent {self.candidate_agent_code_sha})",
            f"- 实验语义: {self.experiment_kind.value}",
            f"- 声明变更: {changes}",
            f"- comparability fingerprint: `{self.comparability_fingerprint}`",
            f"- 结论: {conclusion}",
            "",
            "## 配对四格",
            "",
            "| fail→pass | pass→fail | pass→pass | fail→fail | invalid |",
            "|---|---|---|---|---|",
            "|"
            f" {self.counts.fail_to_pass} | {self.counts.pass_to_fail} |"
            f" {self.counts.pass_to_pass} | {self.counts.fail_to_fail} |"
            f" {self.counts.invalid} |",
            "",
            "## 逐题明细",
            "",
            "| task | attempt | outcome |",
            "|---|---|---|",
        ]
        for trial in self.trials:
            lines.append(
                f"| {trial.task_id} | {trial.attempt} | {trial.outcome_delta.value} |"
            )
        return "\n".join(lines) + "\n"


class PairedExperiment:
    """以 baseline/candidate 两次正式报告构建逐题配对实验。"""

    def __init__(
        self,
        *,
        baseline: EvaluationReport,
        candidate: EvaluationReport,
        declared_changes: tuple[ChangeKind, ...],
        trials: tuple[PairedTrial, ...],
        comparability_fingerprint: str,
        experiment_kind: ExperimentKind,
        injection_fingerprint: str | None = None,
    ) -> None:
        self.baseline = baseline
        self.candidate = candidate
        self.declared_changes = declared_changes
        self.trials = trials
        self.comparability_fingerprint = comparability_fingerprint
        self.experiment_kind = experiment_kind
        self.injection_fingerprint = injection_fingerprint

    @classmethod
    def build(
        cls,
        baseline: EvaluationReport,
        candidate: EvaluationReport,
        declared_changes: Iterable[ChangeKind],
    ) -> PairedExperiment:
        """严格校验可比性后按 ``(task_id, attempt)`` 配对两侧结果。

        校验失败抛出 ``PairedExperimentError``,聚合全部不变量差异,
        不做半成品配对。
        """

        changes = _normalize_changes(declared_changes)
        errors = _comparability_errors(baseline, candidate, changes)
        if errors:
            raise PairedExperimentError(_controlled_reason(errors))
        trials = _pair_trials(baseline, candidate)
        return cls(
            baseline=baseline,
            candidate=candidate,
            declared_changes=changes,
            trials=trials,
            comparability_fingerprint=_comparability_fingerprint(baseline, candidate),
            experiment_kind=_experiment_kind(baseline, candidate),
        )

    def to_report(self) -> PairedExperimentReport:
        """生成严格版本化的可序列化报告。"""

        return PairedExperimentReport(
            baseline_run_id=self.baseline.manifest.run_id,
            candidate_run_id=self.candidate.manifest.run_id,
            experiment_kind=self.experiment_kind,
            baseline_agent_code_sha=self.baseline.manifest.agent_code_sha,
            candidate_agent_code_sha=self.candidate.manifest.agent_code_sha,
            injection_fingerprint=self.injection_fingerprint,
            declared_changes=self.declared_changes,
            comparability_fingerprint=self.comparability_fingerprint,
            trials=self.trials,
            counts=_count_trials(self.trials),
        )


def _normalize_changes(changes: Iterable[ChangeKind]) -> tuple[ChangeKind, ...]:
    normalized = {ChangeKind(change) for change in changes}
    if not normalized:
        raise PairedExperimentError(
            "At least one prompt, compression, or tool change must be declared"
        )
    return tuple(sorted(normalized, key=lambda kind: kind.value))


def _experiment_kind(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
) -> ExperimentKind:
    if (
        baseline.manifest.agent_code_sha
        == candidate.manifest.agent_code_sha
    ):
        return ExperimentKind.CONTROLLED
    return ExperimentKind.REGRESSION


def _comparability_errors(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
    declared_changes: tuple[ChangeKind, ...],
) -> list[str]:
    errors: list[str] = []
    _require_official_for_pairing(baseline, errors, label="Baseline")
    _require_official_for_pairing(candidate, errors, label="Candidate")
    if baseline.manifest.run_id == candidate.manifest.run_id:
        errors.append("Baseline and candidate must use distinct run IDs")
    _compare_catalog_locks(baseline.manifest, candidate.manifest, errors)
    for field_name in _MANIFEST_INVARIANT_FIELDS:
        if getattr(baseline.manifest, field_name) != getattr(candidate.manifest, field_name):
            errors.append(f"Manifest invariant field differs: {field_name}")
    baseline_profile = baseline.manifest.profile
    candidate_profile = candidate.manifest.profile
    for field_name in _PROFILE_INVARIANT_FIELDS:
        if getattr(baseline_profile, field_name) != getattr(candidate_profile, field_name):
            errors.append(f"Profile invariant field differs: {field_name}")
    actual_changes = {
        kind
        for kind, field_name in _PROFILE_CHANGE_FIELDS.items()
        if getattr(baseline_profile, field_name) != getattr(candidate_profile, field_name)
    }
    if actual_changes != set(declared_changes):
        errors.append("Declared change kinds do not match profile version differences")
    if not actual_changes:
        errors.append("Candidate does not change a gate-controlled profile version")
    return errors


def _require_official_for_pairing(
    report: EvaluationReport,
    errors: list[str],
    *,
    label: str,
) -> None:
    if report.status is not ReportStatus.OFFICIAL or report.official_score is None:
        errors.append(f"{label} report is not a complete official report")
        return
    expected_pairs = {
        (task_id, attempt)
        for task_id in report.manifest.task_ids
        for attempt in range(1, report.manifest.repeats + 1)
    }
    actual_pairs = {(result.task_id, result.attempt) for result in report.results}
    if len(report.results) != len(expected_pairs) or actual_pairs != expected_pairs:
        errors.append(f"{label} report must cover every frozen task and repeat")
        return
    if any(not _is_comparable_result(result) for result in report.results):
        errors.append(f"{label} report contains non-official or invalid results")


def _is_comparable_result(result: TaskResult) -> bool:
    return (
        result.official
        and result.validity is ResultValidity.VALID
        and result.verdict in {TaskVerdict.PASSED, TaskVerdict.FAILED}
    )


def _compare_catalog_locks(baseline: Any, candidate: Any, errors: list[str]) -> None:
    for field_name in _CATALOG_LOCK_FIELDS:
        if getattr(baseline.catalog, field_name) != getattr(candidate.catalog, field_name):
            errors.append(f"Catalog lock field differs: {field_name}")


def _pair_trials(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
) -> tuple[PairedTrial, ...]:
    candidate_by_key = {
        (result.task_id, result.attempt): result for result in candidate.results
    }
    trials: list[PairedTrial] = []
    for baseline_result in sorted(baseline.results, key=lambda result: (result.task_id, result.attempt)):
        key = (baseline_result.task_id, baseline_result.attempt)
        candidate_result = candidate_by_key[key]
        trials.append(
            PairedTrial(
                task_id=key[0],
                attempt=key[1],
                baseline_result=baseline_result,
                candidate_result=candidate_result,
                outcome_delta=_outcome_delta(baseline_result, candidate_result),
            )
        )
    return tuple(trials)


def _outcome_delta(
    baseline_result: TaskResult,
    candidate_result: TaskResult,
) -> PairedTrialOutcome:
    if not (
        _is_comparable_result(baseline_result)
        and _is_comparable_result(candidate_result)
    ):
        return PairedTrialOutcome.INVALID
    baseline_passed = baseline_result.verdict is TaskVerdict.PASSED
    candidate_passed = candidate_result.verdict is TaskVerdict.PASSED
    if baseline_passed and candidate_passed:
        return PairedTrialOutcome.PASS_TO_PASS
    if baseline_passed and not candidate_passed:
        return PairedTrialOutcome.PASS_TO_FAIL
    if not baseline_passed and candidate_passed:
        return PairedTrialOutcome.FAIL_TO_PASS
    return PairedTrialOutcome.FAIL_TO_FAIL


def _count_trials(trials: Sequence[PairedTrial]) -> PairedCounts:
    counts = {
        PairedTrialOutcome.FAIL_TO_PASS: 0,
        PairedTrialOutcome.PASS_TO_FAIL: 0,
        PairedTrialOutcome.PASS_TO_PASS: 0,
        PairedTrialOutcome.FAIL_TO_FAIL: 0,
        PairedTrialOutcome.INVALID: 0,
    }
    for trial in trials:
        counts[trial.outcome_delta] += 1
    return PairedCounts(
        fail_to_pass=counts[PairedTrialOutcome.FAIL_TO_PASS],
        pass_to_fail=counts[PairedTrialOutcome.PASS_TO_FAIL],
        pass_to_pass=counts[PairedTrialOutcome.PASS_TO_PASS],
        fail_to_fail=counts[PairedTrialOutcome.FAIL_TO_FAIL],
        invalid=counts[PairedTrialOutcome.INVALID],
    )


def _comparability_fingerprint(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
) -> str:
    return _digest(
        {
            "baseline": _comparability_snapshot(baseline),
            "candidate": _comparability_snapshot(candidate),
        }
    )


def _comparability_snapshot(report: EvaluationReport) -> dict[str, Any]:
    manifest = report.manifest
    profile = manifest.profile
    return {
        "catalog": {
            field_name: getattr(manifest.catalog, field_name)
            for field_name in _CATALOG_LOCK_FIELDS
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


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ChangeKind",
    "HarnessVariant",
    "PairedCounts",
    "PairedExperiment",
    "PairedExperimentError",
    "PairedExperimentReport",
    "PairedTrial",
    "PairedTrialOutcome",
]