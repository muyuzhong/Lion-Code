# Design: Gate V2——comparison.py + gate.py

## 1. 数据流

```text
PairedExperimentReport(counts + trials + kind)
        ↓ compare()
ComparisonResult(kind, outcome, process, efficiency, reasons)
        ↓ decide_gate()
GateV2Result(decision, reasons, comparison)
```

- `compare(report, baseline_process=?, candidate_process=?, thresholds...)`
  纯函数,输入冻结报告;process 校验结果由调用方按 `(task_id, attempt)`
  提供(执行链不落盘 ProcessVerification,本层不扩执行链)。
- `decide_gate(comparison)` 按固定优先级纯判定。

## 2. comparison.py

### 模型(全部 VersionedModel,strict JSON)

```python
class ComparisonSignal(str, Enum): IMPROVED / REGRESSED / NEUTRAL
class GuardrailLevel(str, Enum):   OK / WARN / BLOCKED
class EfficiencyMetric(str, Enum): TURNS / TOKENS / COST / WALL_TIME

class OutcomeComparison:
    fail_to_pass/pass_to_fail/pass_to_pass/fail_to_fail: int
    valid_pairs: int
    net_improvement: int                 # f2p - p2f
    delta_success_rate: float            # net / valid_pairs
    delta_ci_low/delta_ci_high: float|None   # 配对 bootstrap 95% CI
    mcnemar_p_value: float|None          # exact two-sided
    signal: ComparisonSignal
    reasons: tuple[str, ...]

class ProcessPairChange:                 # 一条可审计的 pair 级变化
    task_id, attempt
    kind: NEW_CRITICAL_VETO / NEW_VIOLATION / RESOLVED_VIOLATION
    baseline_status, candidate_status: ProcessVerificationStatus|None
    baseline_types, candidate_types: tuple[ProcessViolationType, ...]

class ProcessComparison:
    paired, unavailable: int
    new_critical_vetoes: tuple[ProcessPairChange, ...]   # → BLOCKED 依据
    new_violations: tuple[ProcessPairChange, ...]
    resolved_violations: tuple[ProcessPairChange, ...]
    regressed_pairs, improved_pairs: int                 # 严重级方向
    gated: bool                                          # 是否提供了校验结果
    signal: ComparisonSignal
    reasons: tuple[str, ...]

class EfficiencyMetricComparison:
    metric: EfficiencyMetric
    baseline_mean/candidate_mean: float|None
    delta_pct: float|None
    guardrail: GuardrailLevel

class EfficiencyComparison:
    metrics: tuple[EfficiencyMetricComparison, ...]
    guardrail: GuardrailLevel
    reasons: tuple[str, ...]

class ComparisonResult:
    kind: ExperimentKind
    outcome: OutcomeComparison
    process: ProcessComparison
    efficiency: EfficiencyComparison
    reasons: tuple[str, ...]             # 聚合摘要
```

### 计算

- `compute_outcome(counts: PairedCounts, *, mcnemar_alpha=0.05,
  min_discordant=3, bootstrap_replicates=2000, ci_alpha=0.05, seed=0)`
  - 有效配对数 = f2p+p2f+p2p+f2f;
  - delta = (f2p-p2f)/valid;
  - McNemar exact two-sided:`p = 2·Σ_{i≤min(b,c)} C(n,i)/2ⁿ`,n=b+c,
    n=0 → None;
  - 配对 bootstrap:单题 delta ∈ {+1,−1,0}(b,c,s 份),重抽样 n 次均值,
    取 alpha/2 与 1-alpha/2 分位;seed 固定保证可复现;
  - signal:确定性规则只用于**保守捕获回归**(pass→fail ≥ min_discordant
    且差 ≥ min_discordant),其次统计回归(p<alpha 且 pass→fail 占优);
    改善必须 McNemar 显著(bootstrap CI 只作效应量上报,不单独判
    IMPROVED)——小样本积极信号(如 4→0)只进 reasons,判 NEUTRAL;
  - reasons 记录触发依据。
- `compare_process(trials, baseline: Mapping[(task_id,attempt),ProcessVerification],
  candidate: Mapping[...])`
  - 严重级:VALID=0 < VIOLATION=1 < CRITICAL_VETO=2;EVIDENCE_UNAVAILABLE
    或缺映射 → unavailable(不计方向);
  - 每 pair 判定 kind + 方向(improved/regressed);
  - signal:有 new_critical → REGRESSED;否则 regressed>improved →
    REGRESSED;improved>regressed 且 regressed==0 → IMPROVED;否则 NEUTRAL。
- `compute_efficiency(trials, *, warn/block_thresholds)`
  - 每指标取两侧均有 agent_run 的 pair,算均值与 delta_pct;
  - delta_pct 对 baseline_mean>0 才有意义;guardrail=max(OK/WARN/BLOCKED);
  - 默认阈值:WARN{turns:.5, tokens:.5, cost:.35, wall:.4},
    BLOCK{turns:2.0, tokens:2.0, cost:3.0, wall:3.0}。
- `compare(report, *, baseline_process=None, candidate_process=None,
  **阈值/seed)` → `ComparisonResult`
  - 未提供 process 映射 → process.gated=False,reason 标注「过程不参与判定」;
  - 未提供 → 不影响 outcome/efficiency。

## 3. gate.py

```python
class GateDecision(str, Enum): IMPROVED / NEUTRAL / REGRESSED / BLOCKED

class GateV2Result(VersionedModel):
    decision: GateDecision
    reasons: tuple[str, ...]
    comparison: ComparisonResult

def decide_gate(comparison: ComparisonResult) -> GateV2Result
```

优先级(固定):

```text
1. kind is UNSUPPORTED_TREATMENT                            → BLOCKED
2. process.new_critical_vetoes 非空                         → BLOCKED
3. outcome.signal is REGRESSED                              → REGRESSED
4. process.regressed_pairs == 0 且 efficiency BLOCKED       → BLOCKED
5. outcome.signal is IMPROVED
   且 process.gated 且 unavailable==0 且 regressed==0       → IMPROVED
6. 其余(效率 WARN 只记录;process 未完整可比 → NEUTRAL)      → NEUTRAL
```

- reasons 逐条中文说明触发/未触发依据,至少包含 decision 的主因;
- outcome IMPROVED 但 process 未完整可比(未测/部分缺失)或退化 → NEUTRAL,
  不硬判 IMPROVED("没有发现退化"≠"没有测");
- 效率 BLOCKED 优先于 outcome IMPROVED(灾难不能被改善绕过),WARN 只记录。

## 4. 测试

- `test_comparison.py`:四格→净改善/δ/CI;McNemar 精确 p 的手工值核对;
  bootstrap 确定性与区间包含真实值;确定性灾难规则;process 三态迁移
  (new critical / new violation / resolved);efficiency 阈值与 None 均值。
- `test_gate_v2.py`:直接覆盖 PRD 6 个验收用例 + 优先级边界(process 退化
  时 IMPROVED 降级 NEUTRAL;效率 BLOCK 升级)。
- 测试造数:自建 `_report(pairs, kind)` 直接构造 `PairedExperimentReport`
  (REGRESSION 免注入证据;UNSUPPORTED 同 code),TaskResult 带 agent_run
  供 efficiency。

## 5. 边界与不做的事

- 不落盘 ProcessVerification 到 TaskResult(不扩执行链);
- 无 tool_calls 指标(TaskResult 无数据源);
- 报告 validator 已保证 counts 与 trials 一致,比较层不再重复校验;
- bootstrap 只做 percentile CI,不做显著性检验。
