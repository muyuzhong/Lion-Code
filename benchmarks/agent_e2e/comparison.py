"""配对实验的比较层:把 PairedExperimentReport 转成可发布门禁的结论。

三层:
- Outcome(主判据):四格计数 → 净改善、delta_success_rate、McNemar
  exact test、配对 bootstrap 置信区间,叠加「确定性灾难规则」——
  小样本下 p 值经常无意义,不能作为唯一门禁依据;
- Process:直接消费 #144 的 ``ProcessVerification``(按 (task_id, attempt)
  由调用方提供,本层不扩执行链),只看新增 critical veto / 新增
  violation / 已有 violation 被消除;
- Efficiency(只观察):平均 turns/tokens/cost/wall time,仅当 outcome
  与 process 不退化时才对明显恶化给出 WARN/BLOCKED guardrail,不把
  「更少工具调用」当成优化目标。

结果模型全部严格版本化,供 gate.py 做固定优先级判定。
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from enum import Enum

from pydantic import Field

from .experiment import (
    ExperimentKind,
    PairedCounts,
    PairedExperimentReport,
    PairedTrial,
)
from .models import AgentRunSummary, VersionedModel
from .process_verifier import (
    ProcessVerification,
    ProcessVerificationStatus,
    ProcessViolationType,
)


class ComparisonSignal(str, Enum):
    """比较层的方向信号(Outcome / Process 共用)。"""

    IMPROVED = "improved"
    REGRESSED = "regressed"
    NEUTRAL = "neutral"


class GuardrailLevel(str, Enum):
    """Efficiency guardrail 级别;只观察,不作为主要优化目标。"""

    OK = "ok"
    WARN = "warn"
    BLOCKED = "blocked"


class EfficiencyMetric(str, Enum):
    """V1 可观测的效率指标(AgentRunSummary 提供;无 tool_calls 数据源)。"""

    TURNS = "turns"
    TOKENS = "tokens"
    COST = "cost_usd"
    WALL_TIME = "wall_time_seconds"


class OutcomeComparison(VersionedModel):
    """Outcome 主判据:四格 + 配对统计 + 信号。"""

    fail_to_pass: int = Field(ge=0)
    pass_to_fail: int = Field(ge=0)
    pass_to_pass: int = Field(ge=0)
    fail_to_fail: int = Field(ge=0)
    valid_pairs: int = Field(ge=0)
    net_improvement: int
    delta_success_rate: float
    delta_ci_low: float | None = None
    delta_ci_high: float | None = None
    mcnemar_p_value: float | None = Field(default=None, ge=0, le=1)
    signal: ComparisonSignal
    reasons: tuple[str, ...] = ()


class ProcessChangeKind(str, Enum):
    """单 pair 的过程迁移方向。"""

    NEW_CRITICAL_VETO = "new_critical_veto"
    NEW_VIOLATION = "new_violation"
    RESOLVED_VIOLATION = "resolved_violation"


class ProcessPairChange(VersionedModel):
    """一条可审计的 pair 级过程变化。"""

    task_id: str = Field(min_length=1, max_length=128)
    attempt: int = Field(ge=1)
    kind: ProcessChangeKind
    baseline_status: ProcessVerificationStatus | None = None
    candidate_status: ProcessVerificationStatus | None = None
    baseline_types: tuple[ProcessViolationType, ...] = ()
    candidate_types: tuple[ProcessViolationType, ...] = ()


class ProcessComparison(VersionedModel):
    """Process 比较:新增 critical veto 是 BLOCKED 的依据。"""

    paired: int = Field(ge=0)
    unavailable: int = Field(ge=0)
    new_critical_vetoes: tuple[ProcessPairChange, ...] = ()
    new_violations: tuple[ProcessPairChange, ...] = ()
    resolved_violations: tuple[ProcessPairChange, ...] = ()
    regressed_pairs: int = Field(ge=0)
    improved_pairs: int = Field(ge=0)
    gated: bool = False
    signal: ComparisonSignal
    reasons: tuple[str, ...] = ()


class EfficiencyMetricComparison(VersionedModel):
    """单指标的平均值与恶化幅度;baseline_mean=0 时 delta 无意义。"""

    metric: EfficiencyMetric
    baseline_mean: float | None = None
    candidate_mean: float | None = None
    delta_pct: float | None = None
    guardrail: GuardrailLevel


class EfficiencyComparison(VersionedModel):
    """效率 guardrail 汇总;WARN 只记录,BLOCKED 由 gate 决定是否升级。"""

    metrics: tuple[EfficiencyMetricComparison, ...] = ()
    guardrail: GuardrailLevel
    reasons: tuple[str, ...] = ()


class ComparisonResult(VersionedModel):
    """比较层的聚合结果,是 gate 判定的唯一输入。"""

    kind: ExperimentKind
    outcome: OutcomeComparison
    process: ProcessComparison
    efficiency: EfficiencyComparison
    reasons: tuple[str, ...] = ()


# 严重级顺序:VALID < VIOLATION < CRITICAL_VETO;EVIDENCE_UNAVAILABLE 不可比。
_SEVERITY_RANK = {
    ProcessVerificationStatus.VALID: 0,
    ProcessVerificationStatus.VIOLATION: 1,
    ProcessVerificationStatus.CRITICAL_VETO: 2,
}

_DEFAULT_WARN_PCT: dict[EfficiencyMetric, float] = {
    EfficiencyMetric.TURNS: 0.50,
    EfficiencyMetric.TOKENS: 0.50,
    EfficiencyMetric.COST: 0.35,
    EfficiencyMetric.WALL_TIME: 0.40,
}
_DEFAULT_BLOCK_PCT: dict[EfficiencyMetric, float] = {
    EfficiencyMetric.TURNS: 2.0,
    EfficiencyMetric.TOKENS: 2.0,
    EfficiencyMetric.COST: 3.0,
    EfficiencyMetric.WALL_TIME: 3.0,
}


def compute_outcome(
    counts: PairedCounts,
    *,
    mcnemar_alpha: float = 0.05,
    min_discordant: int = 3,
    bootstrap_replicates: int = 2000,
    ci_alpha: float = 0.05,
    seed: int = 0,
) -> OutcomeComparison:
    """从四格计数计算 outcome 比较与配对统计。

    信号判定:确定性灾难规则优先(胜方不一致格与差距都 >=
    ``min_discordant``),其次统计规则(McNemar exact p < alpha 且
    方向明确),否则 NEUTRAL。
    """

    b = counts.fail_to_pass
    c = counts.pass_to_fail
    same = counts.pass_to_pass + counts.fail_to_fail
    valid = b + c + same
    net = b - c
    delta = net / valid if valid else 0.0
    p_value = _mcnemar_exact_p(b, c)
    ci_low, ci_high = _bootstrap_delta_ci(
        b,
        c,
        same,
        replicates=bootstrap_replicates,
        alpha=ci_alpha,
        seed=seed,
    )
    signal, reasons = _outcome_signal(
        b,
        c,
        mcnemar_p=p_value,
        mcnemar_alpha=mcnemar_alpha,
        min_discordant=min_discordant,
    )
    return OutcomeComparison(
        fail_to_pass=b,
        pass_to_fail=c,
        pass_to_pass=counts.pass_to_pass,
        fail_to_fail=counts.fail_to_fail,
        valid_pairs=valid,
        net_improvement=net,
        delta_success_rate=delta,
        delta_ci_low=ci_low,
        delta_ci_high=ci_high,
        mcnemar_p_value=p_value,
        signal=signal,
        reasons=reasons,
    )


def compare_process(
    trials: Sequence[PairedTrial],
    baseline: Mapping[tuple[str, int], ProcessVerification] | None,
    candidate: Mapping[tuple[str, int], ProcessVerification] | None,
) -> ProcessComparison:
    """按 pair 比较两侧 ProcessVerification。

    缺映射或 EVIDENCE_UNAVAILABLE 的 pair 计入 ``unavailable`` 且不计
    方向;两侧都可比时按严重级顺序判定迁移方向。
    """

    gated = baseline is not None and candidate is not None
    new_critical: list[ProcessPairChange] = []
    new_violations: list[ProcessPairChange] = []
    resolved: list[ProcessPairChange] = []
    regressed = 0
    improved = 0
    paired = 0
    unavailable = 0
    for trial in trials:
        key = (trial.task_id, trial.attempt)
        baseline_verification = baseline.get(key) if baseline is not None else None
        candidate_verification = candidate.get(key) if candidate is not None else None
        baseline_status = _rankable(baseline_verification)
        candidate_status = _rankable(candidate_verification)
        if baseline_status is None or candidate_status is None:
            unavailable += 1
            continue
        paired += 1
        if (
            baseline_status is not ProcessVerificationStatus.CRITICAL_VETO
            and candidate_status is ProcessVerificationStatus.CRITICAL_VETO
        ):
            new_critical.append(
                _change(
                    trial,
                    kind=ProcessChangeKind.NEW_CRITICAL_VETO,
                    baseline_verification=baseline_verification,
                    candidate_verification=candidate_verification,
                    baseline_status=baseline_status,
                    candidate_status=candidate_status,
                )
            )
        elif (
            baseline_status is ProcessVerificationStatus.VALID
            and candidate_status is ProcessVerificationStatus.VIOLATION
        ):
            new_violations.append(
                _change(
                    trial,
                    kind=ProcessChangeKind.NEW_VIOLATION,
                    baseline_verification=baseline_verification,
                    candidate_verification=candidate_verification,
                    baseline_status=baseline_status,
                    candidate_status=candidate_status,
                )
            )
        elif (
            baseline_status is not ProcessVerificationStatus.VALID
            and candidate_status is ProcessVerificationStatus.VALID
        ):
            resolved.append(
                _change(
                    trial,
                    kind=ProcessChangeKind.RESOLVED_VIOLATION,
                    baseline_verification=baseline_verification,
                    candidate_verification=candidate_verification,
                    baseline_status=baseline_status,
                    candidate_status=candidate_status,
                )
            )
        baseline_rank = _SEVERITY_RANK[baseline_status]
        candidate_rank = _SEVERITY_RANK[candidate_status]
        if candidate_rank > baseline_rank:
            regressed += 1
        elif candidate_rank < baseline_rank:
            improved += 1
    signal, reasons = _process_signal(
        new_critical=new_critical,
        resolved=resolved,
        regressed=regressed,
        improved=improved,
        gated=gated,
    )
    return ProcessComparison(
        paired=paired,
        unavailable=unavailable,
        new_critical_vetoes=tuple(new_critical),
        new_violations=tuple(new_violations),
        resolved_violations=tuple(resolved),
        regressed_pairs=regressed,
        improved_pairs=improved,
        gated=gated,
        signal=signal,
        reasons=reasons,
    )


def compute_efficiency(
    trials: Sequence[PairedTrial],
    *,
    warn_thresholds: Mapping[EfficiencyMetric, float] | None = None,
    block_thresholds: Mapping[EfficiencyMetric, float] | None = None,
) -> EfficiencyComparison:
    """聚合平均效率并给出 guardrail;不评判「更少 = 更好」。

    每指标取两侧都有 agent_run 的 pair;baseline_mean=0 时 delta_pct
    无意义(不触发 guardrail)。默认阈值见 ``_DEFAULT_WARN_PCT`` /
    ``_DEFAULT_BLOCK_PCT``。
    """

    warn = dict(_DEFAULT_WARN_PCT)
    if warn_thresholds is not None:
        warn.update(warn_thresholds)
    block = dict(_DEFAULT_BLOCK_PCT)
    if block_thresholds is not None:
        block.update(block_thresholds)
    rows: list[EfficiencyMetricComparison] = []
    reasons: list[str] = []
    for metric in EfficiencyMetric:
        baseline_values, candidate_values = _metric_pairs(trials, metric)
        if not baseline_values:
            rows.append(
                EfficiencyMetricComparison(metric=metric, guardrail=GuardrailLevel.OK)
            )
            continue
        baseline_mean = sum(baseline_values) / len(baseline_values)
        candidate_mean = sum(candidate_values) / len(candidate_values)
        delta_pct = None
        if baseline_mean > 0:
            delta_pct = (candidate_mean - baseline_mean) / baseline_mean
        level = _guardrail_for(metric, delta_pct, warn, block)
        if level is GuardrailLevel.WARN:
            reasons.append(f"{metric.value} 恶化 {delta_pct:+.1%} → WARN")
        elif level is GuardrailLevel.BLOCKED:
            reasons.append(f"{metric.value} 恶化 {delta_pct:+.1%} → BLOCKED")
        rows.append(
            EfficiencyMetricComparison(
                metric=metric,
                baseline_mean=baseline_mean,
                candidate_mean=candidate_mean,
                delta_pct=delta_pct,
                guardrail=level,
            )
        )
    overall = _max_guardrail(rows)
    if overall is GuardrailLevel.OK:
        reasons.append("效率指标无显著恶化")
    return EfficiencyComparison(
        metrics=tuple(rows),
        guardrail=overall,
        reasons=tuple(reasons),
    )


def compare(
    report: PairedExperimentReport,
    *,
    baseline_process: Mapping[tuple[str, int], ProcessVerification] | None = None,
    candidate_process: Mapping[tuple[str, int], ProcessVerification] | None = None,
    mcnemar_alpha: float = 0.05,
    min_discordant: int = 3,
    bootstrap_replicates: int = 2000,
    ci_alpha: float = 0.05,
    seed: int = 0,
    efficiency_warn_thresholds: Mapping[EfficiencyMetric, float] | None = None,
    efficiency_block_thresholds: Mapping[EfficiencyMetric, float] | None = None,
) -> ComparisonResult:
    """组合三层比较;process 校验结果未提供时该维度不参与判定。"""

    outcome = compute_outcome(
        report.counts,
        mcnemar_alpha=mcnemar_alpha,
        min_discordant=min_discordant,
        bootstrap_replicates=bootstrap_replicates,
        ci_alpha=ci_alpha,
        seed=seed,
    )
    process = compare_process(report.trials, baseline_process, candidate_process)
    efficiency = compute_efficiency(
        report.trials,
        warn_thresholds=efficiency_warn_thresholds,
        block_thresholds=efficiency_block_thresholds,
    )
    return ComparisonResult(
        kind=report.experiment_kind,
        outcome=outcome,
        process=process,
        efficiency=efficiency,
        reasons=(*outcome.reasons, *process.reasons, *efficiency.reasons),
    )


def _mcnemar_exact_p(b: int, c: int) -> float | None:
    """McNemar exact 双侧 p:不一致格 n=b+c 下 X~Binomial(n, 0.5)。"""

    n = b + c
    if n == 0:
        return None
    k = min(b, c)
    p = 2.0 * sum(math.comb(n, i) for i in range(k + 1)) / (2**n)
    return min(p, 1.0)


def _bootstrap_delta_ci(
    b: int,
    c: int,
    same: int,
    *,
    replicates: int,
    alpha: float,
    seed: int,
) -> tuple[float | None, float | None]:
    """配对 bootstrap 的 delta_success_rate 百分位区间(确定性 seed)。"""

    n = b + c + same
    if n == 0:
        return None, None
    deltas = [1] * b + [-1] * c + [0] * same
    rng = random.Random(seed)
    means = [sum(rng.choice(deltas) for _ in range(n)) / n for _ in range(replicates)]
    means.sort()
    low = max(0, int(replicates * alpha / 2))
    high = min(replicates - 1, int(replicates * (1 - alpha / 2)))
    return means[low], means[high]


def _outcome_signal(
    b: int,
    c: int,
    *,
    mcnemar_p: float | None,
    mcnemar_alpha: float,
    min_discordant: int,
) -> tuple[ComparisonSignal, tuple[str, ...]]:
    """确定性灾难规则优先;统计规则其次;否则 NEUTRAL。"""

    if b >= min_discordant and (b - c) >= min_discordant:
        return ComparisonSignal.IMPROVED, (
            f"确定性规则:fail→pass={b} ≥ {min_discordant} 且差 {b - c} ≥ "
            f"{min_discordant}",
        )
    if c >= min_discordant and (c - b) >= min_discordant:
        return ComparisonSignal.REGRESSED, (
            f"确定性规则:pass→fail={c} ≥ {min_discordant} 且差 {c - b} ≥ "
            f"{min_discordant}",
        )
    if mcnemar_p is not None and mcnemar_p < mcnemar_alpha:
        if b > c:
            return ComparisonSignal.IMPROVED, (
                f"McNemar exact p={mcnemar_p:.4f} < {mcnemar_alpha},方向 fail→pass",
            )
        if c > b:
            return ComparisonSignal.REGRESSED, (
                f"McNemar exact p={mcnemar_p:.4f} < {mcnemar_alpha},方向 pass→fail",
            )
    return ComparisonSignal.NEUTRAL, (
        "无显著不一致方向(确定性规则与 McNemar 均未触发)",
    )


def _process_signal(
    *,
    new_critical: Sequence[ProcessPairChange],
    resolved: Sequence[ProcessPairChange],
    regressed: int,
    improved: int,
    gated: bool,
) -> tuple[ComparisonSignal, tuple[str, ...]]:
    if not gated:
        return ComparisonSignal.NEUTRAL, ("未提供过程校验结果,过程维度不参与判定",)
    if new_critical:
        return ComparisonSignal.REGRESSED, (
            f"新增 {len(new_critical)} 个 critical process veto",
        )
    if regressed > improved:
        return ComparisonSignal.REGRESSED, (
            f"过程退化 pair {regressed} > 改善 pair {improved}",
        )
    if improved > regressed and regressed == 0:
        return ComparisonSignal.IMPROVED, (f"过程改善 pair {improved} 个,无退化",)
    if resolved:
        return ComparisonSignal.NEUTRAL, (
            f"已消除 {len(resolved)} 个已有 violation(存在少量过程漂移,不算整体改善)",
        )
    return ComparisonSignal.NEUTRAL, ("过程整体持平",)


def _rankable(
    verification: ProcessVerification | None,
) -> ProcessVerificationStatus | None:
    if verification is None or verification.status not in _SEVERITY_RANK:
        # EVIDENCE_UNAVAILABLE 与缺失一样不可比。
        return None
    return verification.status


def _change(
    trial: PairedTrial,
    *,
    kind: ProcessChangeKind,
    baseline_verification: ProcessVerification,
    candidate_verification: ProcessVerification,
    baseline_status: ProcessVerificationStatus,
    candidate_status: ProcessVerificationStatus,
) -> ProcessPairChange:
    return ProcessPairChange(
        task_id=trial.task_id,
        attempt=trial.attempt,
        kind=kind,
        baseline_status=baseline_status,
        candidate_status=candidate_status,
        baseline_types=_types_of(baseline_verification),
        candidate_types=_types_of(candidate_verification),
    )


def _types_of(
    verification: ProcessVerification,
) -> tuple[ProcessViolationType, ...]:
    return tuple(violation.violation_type for violation in verification.violations)


def _metric_pairs(
    trials: Sequence[PairedTrial],
    metric: EfficiencyMetric,
) -> tuple[list[float], list[float]]:
    baseline_values: list[float] = []
    candidate_values: list[float] = []
    for trial in trials:
        baseline_run = trial.baseline_result.agent_run
        candidate_run = trial.candidate_result.agent_run
        if baseline_run is None or candidate_run is None:
            continue
        baseline_value = _metric_value(baseline_run, metric)
        candidate_value = _metric_value(candidate_run, metric)
        if baseline_value is None or candidate_value is None:
            continue
        baseline_values.append(baseline_value)
        candidate_values.append(candidate_value)
    return baseline_values, candidate_values


def _metric_value(run: AgentRunSummary, metric: EfficiencyMetric) -> float | None:
    if metric is EfficiencyMetric.TURNS:
        return float(run.turns)
    if metric is EfficiencyMetric.TOKENS:
        return float(run.input_tokens + run.output_tokens)
    if metric is EfficiencyMetric.COST:
        return run.cost_usd
    if metric is EfficiencyMetric.WALL_TIME:
        return run.wall_time_seconds
    return None


def _guardrail_for(
    metric: EfficiencyMetric,
    delta_pct: float | None,
    warn: Mapping[EfficiencyMetric, float],
    block: Mapping[EfficiencyMetric, float],
) -> GuardrailLevel:
    if delta_pct is None or delta_pct <= 0:
        return GuardrailLevel.OK
    if delta_pct >= block[metric]:
        return GuardrailLevel.BLOCKED
    if delta_pct >= warn[metric]:
        return GuardrailLevel.WARN
    return GuardrailLevel.OK


def _max_guardrail(rows: Sequence[EfficiencyMetricComparison]) -> GuardrailLevel:
    if any(row.guardrail is GuardrailLevel.BLOCKED for row in rows):
        return GuardrailLevel.BLOCKED
    if any(row.guardrail is GuardrailLevel.WARN for row in rows):
        return GuardrailLevel.WARN
    return GuardrailLevel.OK


__all__ = [
    "ComparisonResult",
    "ComparisonSignal",
    "EfficiencyComparison",
    "EfficiencyMetric",
    "EfficiencyMetricComparison",
    "GuardrailLevel",
    "OutcomeComparison",
    "ProcessChangeKind",
    "ProcessComparison",
    "ProcessPairChange",
    "compare",
    "compare_process",
    "compute_efficiency",
    "compute_outcome",
]
