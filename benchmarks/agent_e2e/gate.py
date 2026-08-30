"""Gate V2:把比较结果转成 Harness 发布门禁的明确结论。

决策优先级固定(见 :func:`decide_gate`),消费 ``ComparisonResult``,
产出 IMPROVED / NEUTRAL / REGRESSED / BLOCKED 之一。

设计要点:p 值不是唯一门禁依据——小样本下统计显著性常无意义,因此
Outcome 信号本身已叠加确定性灾难规则;这里只做固定优先级裁定。
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Any

from .comparison import (
    ComparisonResult,
    ComparisonSignal,
    GuardrailLevel,
    compare,
)
from .experiment import ExperimentKind, PairedExperimentReport
from .models import VersionedModel
from .process_verifier import ProcessVerification


class GateDecision(str, Enum):
    """发布门禁的最终结论。"""

    IMPROVED = "improved"
    NEUTRAL = "neutral"
    REGRESSED = "regressed"
    BLOCKED = "blocked"


class GateV2Result(VersionedModel):
    """一次可复核的门禁判定:结论 + 原因 + 完整的比较明细。"""

    decision: GateDecision
    reasons: tuple[str, ...] = ()
    comparison: ComparisonResult


def decide_gate(comparison: ComparisonResult) -> GateV2Result:
    """按固定优先级判定发布门禁。

    优先级:
    1. 实验不可归因(UNSUPPORTED_TREATMENT)→ BLOCKED;
    2. 新增 critical process veto → BLOCKED;
    3. 明确 Outcome 回归 → REGRESSED;
    4. Process 无退化且效率灾难性恶化(BLOCKED guardrail)→ BLOCKED
       (效率灾难不能被 Outcome 改善提前绕过);
    5. Outcome 改善且 Process 完整可比(已测、无缺失、无退化)→ IMPROVED;
    6. 其余 → NEUTRAL(效率 WARN 只记录;Process 未提供/部分缺失
       不得给出发布级 IMPROVED)。
    """

    # 1. 实验不可归因
    if comparison.kind is ExperimentKind.UNSUPPORTED_TREATMENT:
        return GateV2Result(
            decision=GateDecision.BLOCKED,
            reasons=(
                "实验不可归因(UNSUPPORTED_TREATMENT):声明变量无真实开关或"
                "注入未验证,配对差异不可归因,不能进入发布结论",
            ),
            comparison=comparison,
        )

    # 2. 新增 critical process veto
    if comparison.process.new_critical_vetoes:
        return GateV2Result(
            decision=GateDecision.BLOCKED,
            reasons=(
                f"新增 {len(comparison.process.new_critical_vetoes)} 个 "
                "critical process veto(过程造假/评估完整性破坏),即使 "
                "Outcome 改善也禁止发布",
            ),
            comparison=comparison,
        )

    # 3. 明确 Outcome 回归
    if comparison.outcome.signal is ComparisonSignal.REGRESSED:
        return GateV2Result(
            decision=GateDecision.REGRESSED,
            reasons=(
                f"Outcome 明确回归:{comparison.outcome.reasons[0]}"
                if comparison.outcome.reasons
                else "Outcome 明确回归",
            ),
            comparison=comparison,
        )

    # 4. Process 无退化 + 效率灾难 → BLOCKED(优先于 Outcome 改善)
    if (
        comparison.process.regressed_pairs == 0
        and comparison.efficiency.guardrail is GuardrailLevel.BLOCKED
    ):
        return GateV2Result(
            decision=GateDecision.BLOCKED,
            reasons=(
                "Outcome 未回归且 Process 无退化,但效率灾难性恶化"
                "(BLOCKED guardrail),禁止发布",
            ),
            comparison=comparison,
        )

    # 5. Outcome 改善且 Process 完整可比且无退化 → IMPROVED
    if comparison.outcome.signal is ComparisonSignal.IMPROVED:
        if (
            comparison.process.gated
            and comparison.process.unavailable == 0
            and comparison.process.regressed_pairs == 0
        ):
            return GateV2Result(
                decision=GateDecision.IMPROVED,
                reasons=(
                    f"Outcome 改善({comparison.outcome.reasons[0]})且 "
                    "Process 完整可比、无退化",
                ),
                comparison=comparison,
            )
        if not comparison.process.gated or comparison.process.unavailable > 0:
            return GateV2Result(
                decision=GateDecision.NEUTRAL,
                reasons=(
                    "Outcome 改善但 Process 未完整可比(未测或部分缺失),"
                    "不能给出发布级 IMPROVED",
                ),
                comparison=comparison,
            )
        return GateV2Result(
            decision=GateDecision.NEUTRAL,
            reasons=(
                f"Outcome 改善但 Process 退化 {comparison.process.regressed_pairs} "
                "pair,不满足「Process 不退化」,不判 IMPROVED",
            ),
            comparison=comparison,
        )

    # 6. 其余 → NEUTRAL(效率 WARN 只记录)
    note = ""
    if comparison.efficiency.guardrail is GuardrailLevel.WARN:
        note = "效率指标存在 WARN(仅记录,不改变结论)"
    return GateV2Result(
        decision=GateDecision.NEUTRAL,
        reasons=(f"Outcome 无显著方向,保持 NEUTRAL{(';' + note) if note else ''}",),
        comparison=comparison,
    )


def run_gate_v2(
    report: PairedExperimentReport,
    *,
    baseline_process: Mapping[tuple[str, int], ProcessVerification] | None = None,
    candidate_process: Mapping[tuple[str, int], ProcessVerification] | None = None,
    **compare_kwargs: Any,
) -> GateV2Result:
    """一站式入口:report → compare() → decide_gate()。

    ``**compare_kwargs`` 透传给 :func:`comparison.compare`。
    """

    return decide_gate(
        compare(
            report,
            baseline_process=baseline_process,
            candidate_process=candidate_process,
            **compare_kwargs,
        )
    )


__all__ = ["GateDecision", "GateV2Result", "decide_gate", "run_gate_v2"]
