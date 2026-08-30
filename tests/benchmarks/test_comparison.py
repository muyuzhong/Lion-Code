"""Gate V2 比较层单元测试:Outcome 统计 / Process 迁移 / Efficiency guardrail。"""

from __future__ import annotations

from benchmarks.agent_e2e.comparison import (
    ComparisonSignal,
    EfficiencyMetric,
    GuardrailLevel,
    OutcomeComparison,
    ProcessChangeKind,
    compare,
    compare_process,
    compute_efficiency,
    compute_outcome,
)
from benchmarks.agent_e2e.experiment import (
    ChangeKind,
    ExperimentKind,
    PairedCounts,
    PairedExperimentReport,
    PairedTrial,
    PairedTrialOutcome,
)
from benchmarks.agent_e2e.models import (
    AgentRunSummary,
    ResultValidity,
    TaskResult,
    TaskVerdict,
    VerifierOutcome,
    VerifierResult,
)
from benchmarks.agent_e2e.process_verifier import (
    ProcessSeverity,
    ProcessVerification,
    ProcessVerificationStatus,
    ProcessViolation,
    ProcessViolationType,
)


def _result(
    task_id: str,
    *,
    passed: bool,
    turns: int = 1,
    tokens: int = 0,
    cost: float = 0.0,
    wall: float = 1.0,
) -> TaskResult:
    outcome = VerifierOutcome.PASSED if passed else VerifierOutcome.FAILED
    return TaskResult(
        task_id=task_id,
        attempt=1,
        verdict=TaskVerdict.PASSED if passed else TaskVerdict.FAILED,
        validity=ResultValidity.VALID,
        official=True,
        patch_sha256="b" * 64,
        agent_run=AgentRunSummary(
            final_text_digest="c" * 64,
            stop_reason="completed",
            turns=turns,
            wall_time_seconds=wall,
            input_tokens=tokens,
            output_tokens=0,
            cache_read_tokens=0,
            cost_usd=cost,
        ),
        verifier=VerifierResult(
            outcome=outcome,
            command_summary="hidden verifier",
            exit_code=0 if passed else 1,
            output_digest="d" * 64,
        ),
    )


def _trial(
    index: int,
    baseline_passed: bool,
    candidate_passed: bool,
    *,
    baseline_run: dict | None = None,
    candidate_run: dict | None = None,
    **defaults,
) -> PairedTrial:
    task_id = f"task-{index}"
    baseline_kwargs = {**defaults, **(baseline_run or {})}
    candidate_kwargs = {**defaults, **(candidate_run or {})}
    baseline = _result(task_id, passed=baseline_passed, **baseline_kwargs)
    candidate = _result(task_id, passed=candidate_passed, **candidate_kwargs)
    if baseline_passed and candidate_passed:
        delta = PairedTrialOutcome.PASS_TO_PASS
    elif baseline_passed and not candidate_passed:
        delta = PairedTrialOutcome.PASS_TO_FAIL
    elif not baseline_passed and candidate_passed:
        delta = PairedTrialOutcome.FAIL_TO_PASS
    else:
        delta = PairedTrialOutcome.FAIL_TO_FAIL
    return PairedTrial(
        task_id=task_id,
        attempt=1,
        baseline_result=baseline,
        candidate_result=candidate,
        outcome_delta=delta,
    )


def _report(
    pairs: tuple[tuple[bool, bool], ...],
    *,
    kind: ExperimentKind = ExperimentKind.REGRESSION,
    baseline_run: dict | None = None,
    candidate_run: dict | None = None,
    **defaults,
) -> PairedExperimentReport:
    trials = tuple(
        _trial(
            index,
            baseline_passed,
            candidate_passed,
            baseline_run=baseline_run,
            candidate_run=candidate_run,
            **defaults,
        )
        for index, (baseline_passed, candidate_passed) in enumerate(pairs)
    )
    counts = _count_trials(trials)
    same_code = kind is not ExperimentKind.REGRESSION
    return PairedExperimentReport(
        baseline_run_id="run-baseline",
        candidate_run_id="run-candidate",
        experiment_kind=kind,
        baseline_agent_code_sha="abcdef0",
        candidate_agent_code_sha="abcdef0" if same_code else "deadbee",
        declared_changes=(ChangeKind.PROMPT,),
        comparability_fingerprint="a" * 64,
        trials=trials,
        counts=counts,
    )


def _count_trials(trials: tuple[PairedTrial, ...]) -> PairedCounts:
    values = {outcome: 0 for outcome in PairedTrialOutcome}
    for trial in trials:
        values[trial.outcome_delta] += 1
    return PairedCounts(
        fail_to_pass=values[PairedTrialOutcome.FAIL_TO_PASS],
        pass_to_fail=values[PairedTrialOutcome.PASS_TO_FAIL],
        pass_to_pass=values[PairedTrialOutcome.PASS_TO_PASS],
        fail_to_fail=values[PairedTrialOutcome.FAIL_TO_FAIL],
        invalid=values[PairedTrialOutcome.INVALID],
    )


_CRITICAL_TYPES = {
    ProcessViolationType.VALIDATION_MISSING,
    ProcessViolationType.TEST_TAMPERING,
}


def _verification(
    types: tuple[ProcessViolationType, ...] = (),
) -> ProcessVerification:
    """按类型派生状态合法的 ProcessVerification(TEST_TAMPERING 为 critical)。"""

    violations = tuple(
        ProcessViolation(
            violation_type=violation_type,
            severity=(
                ProcessSeverity.CRITICAL_VETO
                if violation_type in _CRITICAL_TYPES
                else ProcessSeverity.VIOLATION
            ),
            description="fixture",
        )
        for violation_type in types
    )
    if any(
        violation.severity is ProcessSeverity.CRITICAL_VETO for violation in violations
    ):
        status = ProcessVerificationStatus.CRITICAL_VETO
    elif violations:
        status = ProcessVerificationStatus.VIOLATION
    else:
        status = ProcessVerificationStatus.VALID
    return ProcessVerification(
        task_id="task-0",
        attempt=1,
        status=status,
        violations=violations,
    )


def _process_map(
    trials: tuple[PairedTrial, ...],
    types_by_index: dict[int, tuple[ProcessViolationType, ...]],
) -> dict[tuple[str, int], ProcessVerification]:
    return {
        (trial.task_id, trial.attempt): _verification(types_by_index.get(index, ()))
        for index, trial in enumerate(trials)
    }


class TestComputeOutcome:
    def test_net_and_delta(self) -> None:
        outcome = compute_outcome(
            PairedCounts(
                fail_to_pass=8,
                pass_to_fail=1,
                pass_to_pass=10,
                fail_to_fail=5,
                invalid=0,
            )
        )
        assert outcome.valid_pairs == 24
        assert outcome.net_improvement == 7
        assert outcome.delta_success_rate == 7 / 24

    def test_mcnemar_exact_known_value(self) -> None:
        # b=8, c=1 → 2*(C(9,0)+C(9,1))/2^9 = 20/512。
        outcome = compute_outcome(
            PairedCounts(
                fail_to_pass=8,
                pass_to_fail=1,
                pass_to_pass=0,
                fail_to_fail=0,
                invalid=0,
            )
        )
        assert outcome.mcnemar_p_value == 20 / 512

    def test_mcnemar_none_when_no_discordant(self) -> None:
        outcome = compute_outcome(
            PairedCounts(
                fail_to_pass=0,
                pass_to_fail=0,
                pass_to_pass=3,
                fail_to_fail=2,
                invalid=0,
            )
        )
        assert outcome.mcnemar_p_value is None

    def test_bootstrap_ci_deterministic_and_bounded(self) -> None:
        counts = PairedCounts(
            fail_to_pass=8,
            pass_to_fail=1,
            pass_to_pass=10,
            fail_to_fail=5,
            invalid=0,
        )
        first = compute_outcome(counts)
        second = compute_outcome(counts)
        assert first.delta_ci_low == second.delta_ci_low
        assert first.delta_ci_high == second.delta_ci_high
        assert first.delta_ci_low is not None
        assert first.delta_ci_high is not None
        # 区间包围真实 delta,且不出界。
        assert first.delta_ci_low <= first.delta_success_rate <= first.delta_ci_high
        assert -1.0 <= first.delta_ci_low <= first.delta_ci_high <= 1.0

    def test_ci_none_when_no_valid_pairs(self) -> None:
        outcome = compute_outcome(
            PairedCounts(
                fail_to_pass=0,
                pass_to_fail=0,
                pass_to_pass=0,
                fail_to_fail=0,
                invalid=2,
            )
        )
        assert outcome.delta_ci_low is None
        assert outcome.delta_ci_high is None
        assert outcome.signal is ComparisonSignal.NEUTRAL

    def test_small_sample_improvement_is_neutral_with_signal(self) -> None:
        # fail→pass=4, pass→fail=0:小样本积极信号但统计证据不足 →
        # 只记 positive signal,不直接判 IMPROVED(阻止过早相信变好)。
        outcome = compute_outcome(
            PairedCounts(
                fail_to_pass=4,
                pass_to_fail=0,
                pass_to_pass=10,
                fail_to_fail=0,
                invalid=0,
            )
        )
        assert outcome.signal is ComparisonSignal.NEUTRAL
        assert "正向倾向" in outcome.reasons[0]

    def test_tiny_sample_improvement_not_improved(self) -> None:
        # b=3, c=0:McNemar p=0.25 不显著,CI 全为正也不判 IMPROVED
        # ——3 个样本不足以宣称变好,只记 positive signal。
        outcome = compute_outcome(
            PairedCounts(
                fail_to_pass=3,
                pass_to_fail=0,
                pass_to_pass=0,
                fail_to_fail=0,
                invalid=0,
            )
        )
        assert outcome.mcnemar_p_value == 0.25
        assert outcome.signal is ComparisonSignal.NEUTRAL
        assert "正向倾向" in outcome.reasons[0]

    def test_deterministic_regression_small_sample(self) -> None:
        # pass→fail=3, fail→pass=0:确定性灾难规则直接判 REGRESSED。
        outcome = compute_outcome(
            PairedCounts(
                fail_to_pass=0,
                pass_to_fail=3,
                pass_to_pass=5,
                fail_to_fail=5,
                invalid=0,
            )
        )
        assert outcome.signal is ComparisonSignal.REGRESSED

    def test_regression_sensitive_with_one_counter_improvement(self) -> None:
        # fail→pass=1, pass→fail=6:回归侧敏感,确定性规则仍捕获。
        outcome = compute_outcome(
            PairedCounts(
                fail_to_pass=1,
                pass_to_fail=6,
                pass_to_pass=5,
                fail_to_fail=3,
                invalid=0,
            )
        )
        assert outcome.signal is ComparisonSignal.REGRESSED

    def test_marginal_asymmetry_is_neutral(self) -> None:
        # b=8, c=7:差距太小,p≈1,确定性与统计都不触发。
        outcome = compute_outcome(
            PairedCounts(
                fail_to_pass=8,
                pass_to_fail=7,
                pass_to_pass=5,
                fail_to_fail=5,
                invalid=0,
            )
        )
        assert outcome.signal is ComparisonSignal.NEUTRAL

    def test_statistical_path_when_deterministic_disabled(self) -> None:
        # 用极大 min_discordant 关掉确定性规则:b=6,c=0,p=2/64<0.05。
        outcome = compute_outcome(
            PairedCounts(
                fail_to_pass=6,
                pass_to_fail=0,
                pass_to_pass=5,
                fail_to_fail=5,
                invalid=0,
            ),
            min_discordant=100,
        )
        assert outcome.signal is ComparisonSignal.IMPROVED
        assert outcome.mcnemar_p_value == 2 / 64

    def test_outcome_round_trip(self) -> None:
        outcome = compute_outcome(
            PairedCounts(
                fail_to_pass=4,
                pass_to_fail=0,
                pass_to_pass=5,
                fail_to_fail=5,
                invalid=0,
            )
        )
        restored = OutcomeComparison.from_json(outcome.canonical_json())
        assert restored == outcome


class TestCompareProcess:
    def test_new_critical_veto_recorded(self) -> None:
        report = _report(
            ((False, True), (True, True)),
        )
        baseline = _process_map(report.trials, {})
        candidate = _process_map(
            report.trials,
            {0: (ProcessViolationType.TEST_TAMPERING,)},
        )
        comparison = compare_process(report.trials, baseline, candidate)
        assert len(comparison.new_critical_vetoes) == 1
        change = comparison.new_critical_vetoes[0]
        assert change.kind is ProcessChangeKind.NEW_CRITICAL_VETO
        assert change.candidate_types == (ProcessViolationType.TEST_TAMPERING,)
        assert comparison.signal is ComparisonSignal.REGRESSED

    def test_new_violation_recorded(self) -> None:
        report = _report(((False, True), (True, True)))
        baseline = _process_map(report.trials, {})
        candidate = _process_map(
            report.trials,
            {0: (ProcessViolationType.REPEATED_TOOL_CALL,)},
        )
        comparison = compare_process(report.trials, baseline, candidate)
        assert len(comparison.new_violations) == 1
        assert comparison.regressed_pairs == 1
        assert comparison.signal is ComparisonSignal.REGRESSED

    def test_resolved_violation_recorded(self) -> None:
        report = _report(((False, True), (True, True)))
        baseline = _process_map(
            report.trials,
            {0: (ProcessViolationType.REPEATED_TOOL_CALL,)},
        )
        candidate = _process_map(report.trials, {})
        comparison = compare_process(report.trials, baseline, candidate)
        assert len(comparison.resolved_violations) == 1
        assert comparison.improved_pairs == 1
        assert comparison.signal is ComparisonSignal.IMPROVED

    def test_missing_pair_is_unavailable(self) -> None:
        report = _report(((False, True), (True, True)))
        baseline = _process_map(report.trials, {})
        # candidate 缺一个 pair。
        candidate = {
            (trial.task_id, trial.attempt): _verification()
            for trial in report.trials[:1]
        }
        comparison = compare_process(report.trials, baseline, candidate)
        assert comparison.unavailable == 1
        assert comparison.paired == 1

    def test_evidence_unavailable_is_not_comparable(self) -> None:
        report = _report(((False, True),))
        degraded = ProcessVerification(
            task_id="x",
            attempt=1,
            status=ProcessVerificationStatus.EVIDENCE_UNAVAILABLE,
        )
        baseline = {(report.trials[0].task_id, 1): degraded}
        candidate = {(report.trials[0].task_id, 1): _verification()}
        comparison = compare_process(report.trials, baseline, candidate)
        assert comparison.unavailable == 1
        assert comparison.paired == 0

    def test_not_gated_is_neutral(self) -> None:
        report = _report(((False, True),))
        comparison = compare_process(report.trials, None, None)
        assert comparison.gated is False
        assert comparison.signal is ComparisonSignal.NEUTRAL
        assert "不参与判定" in comparison.reasons[0]

    def test_same_critical_not_new(self) -> None:
        report = _report(((False, True),))
        baseline = _process_map(
            report.trials,
            {0: (ProcessViolationType.TEST_TAMPERING,)},
        )
        candidate = _process_map(
            report.trials,
            {0: (ProcessViolationType.TEST_TAMPERING,)},
        )
        comparison = compare_process(report.trials, baseline, candidate)
        assert comparison.new_critical_vetoes == ()
        assert comparison.regressed_pairs == 0


class TestComputeEfficiency:
    def test_cost_warn_at_plus_eighty_percent(self) -> None:
        report = _report(
            ((False, True), (True, True), (True, False)),
            baseline_run={"cost": 1.0},
            candidate_run={"cost": 1.8},
        )
        efficiency = compute_efficiency(report.trials)
        cost_row = next(
            row for row in efficiency.metrics if row.metric is EfficiencyMetric.COST
        )
        assert cost_row.delta_pct == 0.8
        assert cost_row.guardrail is GuardrailLevel.WARN
        assert efficiency.guardrail is GuardrailLevel.WARN

    def test_extreme_cost_blocks(self) -> None:
        report = _report(
            ((False, True), (True, True)),
            baseline_run={"cost": 1.0},
            candidate_run={"cost": 4.0},
        )
        efficiency = compute_efficiency(report.trials)
        cost_row = next(
            row for row in efficiency.metrics if row.metric is EfficiencyMetric.COST
        )
        assert cost_row.guardrail is GuardrailLevel.BLOCKED
        assert efficiency.guardrail is GuardrailLevel.BLOCKED

    def test_zero_baseline_has_no_delta(self) -> None:
        report = _report(
            ((False, True), (True, True)),
            baseline_run={"cost": 0.0},
            candidate_run={"cost": 0.0},
        )
        efficiency = compute_efficiency(report.trials)
        cost_row = next(
            row for row in efficiency.metrics if row.metric is EfficiencyMetric.COST
        )
        assert cost_row.delta_pct is None
        assert cost_row.guardrail is GuardrailLevel.OK

    def test_custom_threshold_overrides_default(self) -> None:
        report = _report(
            ((False, True), (True, True)),
            baseline_run={"cost": 1.0},
            candidate_run={"cost": 1.8},
        )
        efficiency = compute_efficiency(
            report.trials,
            warn_thresholds={EfficiencyMetric.COST: 1.0},
        )
        cost_row = next(
            row for row in efficiency.metrics if row.metric is EfficiencyMetric.COST
        )
        assert cost_row.guardrail is GuardrailLevel.OK

    def test_turns_metric_aggregates(self) -> None:
        report = _report(
            ((False, True), (True, True)),
            baseline_run={"turns": 10},
            candidate_run={"turns": 12},
        )
        efficiency = compute_efficiency(report.trials)
        turns_row = next(
            row for row in efficiency.metrics if row.metric is EfficiencyMetric.TURNS
        )
        assert turns_row.baseline_mean == 10.0
        assert turns_row.candidate_mean == 12.0
        assert turns_row.delta_pct == 0.2


class TestCompare:
    def test_composes_all_layers(self) -> None:
        report = _report(
            ((False, True), (True, False), (True, True), (False, False)),
            baseline_run={"cost": 1.0},
            candidate_run={"cost": 1.0},
        )
        baseline = _process_map(report.trials, {})
        candidate = _process_map(report.trials, {})
        result = compare(
            report,
            baseline_process=baseline,
            candidate_process=candidate,
        )
        assert result.kind is ExperimentKind.REGRESSION
        assert result.outcome.valid_pairs == 4
        assert result.process.paired == 4
        assert result.process.gated is True
        assert result.efficiency.guardrail is GuardrailLevel.OK
        assert result.reasons

    def test_without_process_marks_ungated(self) -> None:
        report = _report(((False, True), (True, True)))
        result = compare(report)
        assert result.process.gated is False
        assert result.process.signal is ComparisonSignal.NEUTRAL
