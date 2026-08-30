"""Gate V2 门禁判定单元测试:PRD 6 个验收用例 + 固定优先级边界。"""

from __future__ import annotations

from benchmarks.agent_e2e.comparison import (
    ComparisonSignal,
    EfficiencyMetric,
    GuardrailLevel,
)
from benchmarks.agent_e2e.experiment import ExperimentKind
from benchmarks.agent_e2e.gate import (
    GateDecision,
    GateV2Result,
    decide_gate,
    run_gate_v2,
)
from benchmarks.agent_e2e.process_verifier import ProcessViolationType
from tests.benchmarks.test_comparison import (
    _process_map,
    _report,
    _verification,
)

# 验收用例 1/3 的「明显改善」四格:f2p=8, p2f=1, p2p=10, f2f=5。
_IMPROVED_PAIRS = (
    ((False, True),) * 8
    + ((True, False),)
    + ((True, True),) * 10
    + ((False, False),) * 5
)
# 验收用例 2 的「明确回归」四格:f2p=1, p2f=6, p2p=5, f2f=3。
_REGRESSED_PAIRS = (
    ((False, True),)
    + ((True, False),) * 6
    + ((True, True),) * 5
    + ((False, False),) * 3
)
# 验收用例 4/5 的「基本持平」四格:f2p=2, p2f=2, p2p=5, f2f=5。
_NEUTRAL_PAIRS = (
    ((False, True),) * 2
    + ((True, False),) * 2
    + ((True, True),) * 5
    + ((False, False),) * 5
)


def _valid_process(report):
    """两侧全部 VALID,无 process 变化。"""

    return _process_map(report.trials, {}), _process_map(report.trials, {})


class TestAcceptanceCases:
    def test_case1_improved_without_process_regression(self) -> None:
        report = _report(_IMPROVED_PAIRS)
        baseline, candidate = _valid_process(report)
        result = run_gate_v2(
            report,
            baseline_process=baseline,
            candidate_process=candidate,
        )
        assert result.decision is GateDecision.IMPROVED
        assert result.comparison.outcome.signal is ComparisonSignal.IMPROVED

    def test_case2_regressed(self) -> None:
        report = _report(_REGRESSED_PAIRS)
        result = run_gate_v2(report)
        assert result.decision is GateDecision.REGRESSED

    def test_case3_outcome_improved_but_new_critical_veto_blocks(self) -> None:
        report = _report(_IMPROVED_PAIRS)
        baseline = _process_map(report.trials, {})
        candidate = _process_map(
            report.trials,
            {0: (ProcessViolationType.TEST_TAMPERING,)},
        )
        result = run_gate_v2(
            report,
            baseline_process=baseline,
            candidate_process=candidate,
        )
        assert result.decision is GateDecision.BLOCKED
        assert len(result.comparison.process.new_critical_vetoes) == 1

    def test_case4_neutral_with_positive_process_signal(self) -> None:
        report = _report(_NEUTRAL_PAIRS)
        baseline = _process_map(
            report.trials,
            {
                0: (ProcessViolationType.REPEATED_TOOL_CALL,),
                1: (ProcessViolationType.REPEATED_TOOL_CALL,),
            },
        )
        candidate = _process_map(report.trials, {})
        result = run_gate_v2(
            report,
            baseline_process=baseline,
            candidate_process=candidate,
        )
        # Outcome 持平 + Process 改善 → NEUTRAL,不硬判 IMPROVED。
        assert result.decision is GateDecision.NEUTRAL
        assert result.comparison.process.signal is ComparisonSignal.IMPROVED
        assert result.comparison.process.improved_pairs == 2

    def test_case5_neutral_with_cost_warn(self) -> None:
        report = _report(
            _NEUTRAL_PAIRS,
            baseline_run={"cost": 1.0},
            candidate_run={"cost": 1.8},
        )
        result = run_gate_v2(report)
        assert result.decision is GateDecision.NEUTRAL
        assert result.comparison.efficiency.guardrail is GuardrailLevel.WARN
        cost_row = next(
            row
            for row in result.comparison.efficiency.metrics
            if row.metric is EfficiencyMetric.COST
        )
        assert cost_row.delta_pct == 0.8

    def test_case6_unsupported_treatment_blocks(self) -> None:
        report = _report(
            _IMPROVED_PAIRS,
            kind=ExperimentKind.UNSUPPORTED_TREATMENT,
        )
        result = run_gate_v2(report)
        assert result.decision is GateDecision.BLOCKED
        assert "不可归因" in result.reasons[0]


class TestPriorityEdges:
    def test_improved_outcome_with_process_regression_is_neutral(self) -> None:
        # Outcome 改善但存在非 critical 的 process 退化 → 不满足「Process 不退化」。
        report = _report(_IMPROVED_PAIRS)
        baseline = _process_map(report.trials, {})
        candidate = _process_map(
            report.trials,
            {0: (ProcessViolationType.REPEATED_TOOL_CALL,)},
        )
        result = run_gate_v2(
            report,
            baseline_process=baseline,
            candidate_process=candidate,
        )
        assert result.decision is GateDecision.NEUTRAL
        assert result.comparison.outcome.signal is ComparisonSignal.IMPROVED
        assert "Process 退化" in result.reasons[0]

    def test_neutral_outcome_with_efficiency_block_blocks(self) -> None:
        report = _report(
            _NEUTRAL_PAIRS,
            baseline_run={"cost": 1.0},
            candidate_run={"cost": 4.0},
        )
        result = run_gate_v2(report)
        assert result.decision is GateDecision.BLOCKED
        assert result.comparison.efficiency.guardrail is GuardrailLevel.BLOCKED

    def test_unsupported_takes_precedence_over_critical_veto(self) -> None:
        # 优先级 1 在 2 之前:即使有 critical veto 也先判「实验不可归因」。
        report = _report(
            _IMPROVED_PAIRS,
            kind=ExperimentKind.UNSUPPORTED_TREATMENT,
        )
        baseline = _process_map(report.trials, {})
        candidate = _process_map(
            report.trials,
            {0: (ProcessViolationType.TEST_TAMPERING,)},
        )
        result = run_gate_v2(
            report,
            baseline_process=baseline,
            candidate_process=candidate,
        )
        assert result.decision is GateDecision.BLOCKED
        assert "不可归因" in result.reasons[0]

    def test_regressed_outcome_precedes_efficiency_block(self) -> None:
        # 明确回归比效率灾难优先(优先级 3 在 5 之前)。
        report = _report(
            _REGRESSED_PAIRS,
            baseline_run={"cost": 1.0},
            candidate_run={"cost": 4.0},
        )
        result = run_gate_v2(report)
        assert result.decision is GateDecision.REGRESSED

    def test_ungated_process_not_improved(self) -> None:
        # Process 完全没测 → 不得给出发布级 IMPROVED(「没有发现退化」
        # 与「没有测」不是一回事)。
        report = _report(_IMPROVED_PAIRS)
        result = run_gate_v2(report)
        assert result.decision is GateDecision.NEUTRAL
        assert result.comparison.process.gated is False
        assert "未完整可比" in result.reasons[0]

    def test_partial_process_not_improved(self) -> None:
        # Process 部分缺失(unavailable>0)→ 同样不能 IMPROVED。
        report = _report(_IMPROVED_PAIRS)
        baseline = _process_map(report.trials, {})
        candidate = {
            (trial.task_id, trial.attempt): _verification()
            for trial in report.trials[: len(report.trials) - 1]
        }
        result = run_gate_v2(
            report,
            baseline_process=baseline,
            candidate_process=candidate,
        )
        assert result.decision is GateDecision.NEUTRAL
        assert result.comparison.process.unavailable == 1
        assert "未完整可比" in result.reasons[0]

    def test_improved_outcome_with_efficiency_block_blocks(self) -> None:
        # 效率灾难不能被 Outcome 改善提前绕过:cost +300% → BLOCKED。
        report = _report(
            _IMPROVED_PAIRS,
            baseline_run={"cost": 1.0},
            candidate_run={"cost": 4.0},
        )
        baseline, candidate = _valid_process(report)
        result = run_gate_v2(
            report,
            baseline_process=baseline,
            candidate_process=candidate,
        )
        assert result.decision is GateDecision.BLOCKED
        assert result.comparison.efficiency.guardrail is GuardrailLevel.BLOCKED
        assert result.comparison.outcome.signal is ComparisonSignal.IMPROVED


class TestGateV2Result:
    def test_json_round_trip(self) -> None:
        report = _report(_IMPROVED_PAIRS)
        result = run_gate_v2(report)
        restored = GateV2Result.from_json(result.canonical_json())
        assert restored == result

    def test_kwargs_pass_through_to_compare(self) -> None:
        # 用极大 min_discordant 关掉确定性规则后,b=6,c=0 走统计路径。
        report = _report(
            ((False, True),) * 6 + ((True, True),) * 5 + ((False, False),) * 5
        )
        result = run_gate_v2(report, min_discordant=100)
        assert result.comparison.outcome.signal is ComparisonSignal.IMPROVED

    def test_decide_gate_pure_on_comparison(self) -> None:
        report = _report(_NEUTRAL_PAIRS)
        first = run_gate_v2(report)
        second = decide_gate(first.comparison)
        assert second.decision == first.decision
