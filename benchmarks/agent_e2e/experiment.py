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
    InjectionEvidence,
    ReportStatus,
    RequestedVariant,
    ResultValidity,
    RunInjectionEvidence,
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

    - ``CONTROLLED``:两侧 agent_code_sha 相同、injection 证据证明
      声明的每个维度在两侧都真实命中且注入了不同内容 →
      可以谈「该机制导致的变化」;
    - ``REGRESSION``:Harness 代码版本不同 → 只能谈「版本整体是否
      回归」,不能归因到具体机制;
    - ``UNSUPPORTED_TREATMENT``:声明了变量但无真实运行开关或注入
      未发生(如 compression、未命中映射、run 级证据不一致)→
      配对差异不可归因。
    """

    CONTROLLED = "controlled"
    REGRESSION = "regression"
    UNSUPPORTED_TREATMENT = "unsupported_treatment"


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
        comparable = _is_comparable_result(
            self.baseline_result
        ) and _is_comparable_result(self.candidate_result)
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
    baseline_injection: RunInjectionEvidence | None = None
    candidate_injection: RunInjectionEvidence | None = None
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
        same_code = self.baseline_agent_code_sha == self.candidate_agent_code_sha
        if self.experiment_kind is ExperimentKind.CONTROLLED and not same_code:
            raise ValueError("Controlled experiments require identical agent code")
        if self.experiment_kind is ExperimentKind.REGRESSION and same_code:
            raise ValueError("Regression comparisons require different agent code")
        if (
            self.experiment_kind is ExperimentKind.CONTROLLED
            and self.injection_fingerprint is None
        ):
            raise ValueError("Controlled experiments require an injection fingerprint")
        if self.experiment_kind is ExperimentKind.CONTROLLED and (
            self.baseline_injection is None or self.candidate_injection is None
        ):
            raise ValueError(
                "Controlled experiments require run injection evidence on both sides"
            )
        if (
            self.experiment_kind is ExperimentKind.UNSUPPORTED_TREATMENT
            and not same_code
        ):
            raise ValueError(
                "Unsupported-treatment comparisons require identical agent code"
            )
        return self

    def render_markdown(self) -> str:
        """生成中文四格摘要报告,按实验语义区分结论措辞。"""

        changes = ", ".join(kind.value for kind in self.declared_changes)
        if self.experiment_kind is ExperimentKind.CONTROLLED:
            conclusion = (
                "受控实验(两侧 agent 代码相同且注入已验证生效):配对"
                f"差异可归因于声明变更 [{changes}] 的机制效果。"
            )
        elif self.experiment_kind is ExperimentKind.UNSUPPORTED_TREATMENT:
            conclusion = (
                "同代码但声明变量无真实运行开关或注入未生效"
                f"([{changes}] 未验证 treatment):配对差异"
                "**不可**归因于该机制;仅可视为 declared-only 观察。"
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
            f"- injection fingerprint: `{self.injection_fingerprint or 'N/A'}`",
            f"- baseline 注入: {_render_run_injection(self.baseline_injection)}",
            f"- candidate 注入: {_render_run_injection(self.candidate_injection)}",
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
        baseline_injection: RunInjectionEvidence | None = None,
        candidate_injection: RunInjectionEvidence | None = None,
    ) -> None:
        self.baseline = baseline
        self.candidate = candidate
        self.declared_changes = declared_changes
        self.trials = trials
        self.comparability_fingerprint = comparability_fingerprint
        self.experiment_kind = experiment_kind
        self.injection_fingerprint = injection_fingerprint
        self.baseline_injection = baseline_injection
        self.candidate_injection = candidate_injection

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
        baseline_injection = _validate_run_injection(baseline)
        candidate_injection = _validate_run_injection(candidate)
        return cls(
            baseline=baseline,
            candidate=candidate,
            declared_changes=changes,
            trials=trials,
            comparability_fingerprint=_comparability_fingerprint(baseline, candidate),
            experiment_kind=_experiment_kind(
                baseline,
                candidate,
                baseline_injection,
                candidate_injection,
                changes,
            ),
            injection_fingerprint=_injection_fingerprint(
                baseline_injection, candidate_injection
            ),
            baseline_injection=baseline_injection,
            candidate_injection=candidate_injection,
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
            baseline_injection=self.baseline_injection,
            candidate_injection=self.candidate_injection,
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
    baseline_injection: RunInjectionEvidence | None,
    candidate_injection: RunInjectionEvidence | None,
    declared_changes: tuple[ChangeKind, ...],
) -> ExperimentKind:
    """判断配对实验的因果语义,要求声明的每个维度真的发生 treatment。

    CONTROLLED 需要同时满足:
    - 两侧 agent 代码相同;
    - 声明变更不含 compression(compression 无真实运行开关);
    - 两侧都有可用的 run 级注入证据;
    - 每个声明维度都在两侧命中(hit)且注入内容摘要不同。
    否则降级为 UNSUPPORTED_TREATMENT(同代码但 treatment 未发生)
    或 REGRESSION(跨代码版本)。
    """

    same_code = baseline.manifest.agent_code_sha == candidate.manifest.agent_code_sha
    if not same_code:
        return ExperimentKind.REGRESSION
    if ChangeKind.COMPRESSION in declared_changes:
        # compression 只有声明没有运行开关,永不进入受控因果实验。
        return ExperimentKind.UNSUPPORTED_TREATMENT
    if baseline_injection is None or candidate_injection is None:
        return ExperimentKind.UNSUPPORTED_TREATMENT
    for kind in declared_changes:
        if not _dimension_verified(kind, baseline_injection, candidate_injection):
            # 声明的维度没有在两侧同时命中且注入不同内容 =
            # 该 treatment 未被验证,不能归因。
            return ExperimentKind.UNSUPPORTED_TREATMENT
    return ExperimentKind.CONTROLLED


def _dimension_verified(
    kind: ChangeKind,
    baseline: RunInjectionEvidence,
    candidate: RunInjectionEvidence,
) -> bool:
    """单个声明维度是否在两侧都真的注入了不同的配置。"""

    if kind is ChangeKind.PROMPT:
        return (
            baseline.resolved_variant.prompt_hit
            and candidate.resolved_variant.prompt_hit
            and baseline.prompt_sha256 is not None
            and candidate.prompt_sha256 is not None
            and baseline.prompt_sha256 != candidate.prompt_sha256
        )
    if kind is ChangeKind.TOOL_POLICY:
        return (
            baseline.resolved_variant.tool_policy_hit
            and candidate.resolved_variant.tool_policy_hit
            and baseline.tool_policy_sha256 is not None
            and candidate.tool_policy_sha256 is not None
            and baseline.tool_policy_sha256 != candidate.tool_policy_sha256
        )
    return False


def _validate_run_injection(
    report: EvaluationReport,
) -> RunInjectionEvidence | None:
    """校验整个 run 的注入证据一致,返回 run 级证据聚合。

    任一 task × attempt 缺失/畸形证据、requested 与 manifest profile
    声明不一致、或 resolved/fingerprint 与其他结果不一致,整个 run
    视为没有可用的注入证据(返回 None)。
    """

    expected_requested = RequestedVariant(
        prompt_version=report.manifest.profile.prompt_version,
        tool_policy_version=report.manifest.profile.tool_policy_version,
        compression_version=report.manifest.profile.compression_version,
    )
    agreed: RunInjectionEvidence | None = None
    for result in report.results:
        evidence = _evidence_of_result(result)
        if evidence is None or evidence.requested != expected_requested:
            return None
        if agreed is None:
            agreed = RunInjectionEvidence(
                requested=evidence.requested,
                resolved_variant=evidence.resolved_variant,
                injection_fingerprint=evidence.injection_fingerprint,
                prompt_sha256=evidence.prompt_sha256,
                tool_policy_sha256=evidence.tool_policy_sha256,
                result_count=1,
            )
            continue
        if (
            evidence.resolved_variant != agreed.resolved_variant
            or evidence.injection_fingerprint != agreed.injection_fingerprint
            or evidence.prompt_sha256 != agreed.prompt_sha256
            or evidence.tool_policy_sha256 != agreed.tool_policy_sha256
        ):
            return None
        agreed = agreed.model_copy(update={"result_count": agreed.result_count + 1})
    return agreed


def _evidence_of_result(result: TaskResult) -> InjectionEvidence | None:
    """读取单条 task result 携带的注入证据;缺失或畸形返回 None。"""

    raw = result.extensions.get("injection_evidence")
    if isinstance(raw, InjectionEvidence):
        return raw
    if isinstance(raw, dict):
        try:
            return InjectionEvidence.from_dict(raw)
        except Exception:
            return None
    return None


def _injection_fingerprint(
    baseline_injection: RunInjectionEvidence | None,
    candidate_injection: RunInjectionEvidence | None,
) -> str | None:
    """两侧注入指纹不同时返回复合指纹;否则 None(未发生 treatment)。"""

    if baseline_injection is None or candidate_injection is None:
        return None
    baseline_fp = baseline_injection.injection_fingerprint
    candidate_fp = candidate_injection.injection_fingerprint
    if baseline_fp is None or candidate_fp is None or baseline_fp == candidate_fp:
        return None
    return _digest({"baseline": baseline_fp, "candidate": candidate_fp})


def _render_run_injection(evidence: RunInjectionEvidence | None) -> str:
    """报告里展示 run 级注入证据的可读摘要。"""

    if evidence is None:
        return "无有效注入证据(UNSUPPORTED)"
    hits: list[str] = []
    if evidence.prompt_sha256 is not None:
        hits.append("prompt")
    if evidence.tool_policy_sha256 is not None:
        hits.append("tool_policy")
    injected = ", ".join(hits) if hits else "无"
    fingerprint = evidence.injection_fingerprint or "N/A"
    return (
        f"命中 [{injected}],fingerprint `{fingerprint}`,"
        f"{evidence.result_count} 个结果一致"
    )


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
        if getattr(baseline.manifest, field_name) != getattr(
            candidate.manifest, field_name
        ):
            errors.append(f"Manifest invariant field differs: {field_name}")
    baseline_profile = baseline.manifest.profile
    candidate_profile = candidate.manifest.profile
    for field_name in _PROFILE_INVARIANT_FIELDS:
        if getattr(baseline_profile, field_name) != getattr(
            candidate_profile, field_name
        ):
            errors.append(f"Profile invariant field differs: {field_name}")
    actual_changes = {
        kind
        for kind, field_name in _PROFILE_CHANGE_FIELDS.items()
        if getattr(baseline_profile, field_name)
        != getattr(candidate_profile, field_name)
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
        if getattr(baseline.catalog, field_name) != getattr(
            candidate.catalog, field_name
        ):
            errors.append(f"Catalog lock field differs: {field_name}")


def _pair_trials(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
) -> tuple[PairedTrial, ...]:
    candidate_by_key = {
        (result.task_id, result.attempt): result for result in candidate.results
    }
    trials: list[PairedTrial] = []
    for baseline_result in sorted(
        baseline.results, key=lambda result: (result.task_id, result.attempt)
    ):
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
            for field_name in (
                *_PROFILE_INVARIANT_FIELDS,
                *_PROFILE_CHANGE_FIELDS.values(),
            )
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
