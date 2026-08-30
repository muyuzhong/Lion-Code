# PRD: Gate V2——配对比较、统计判定与 Harness 发布门禁

> 来源:用户第五轮规划明确指示——前三轮 PR(#143 配对实验骨架 / #144
> 测量信号真实性 / #145 treatment + Verified 主链闭环 + 执行上下文
> 不变量)已解决「实验可信不可信」,本 PR 解决「可信实验出来以后,
> 该不该合这个 Harness 改动」。**只做 comparison.py + Gate V2,不扩
> 执行链,不做 regression_probe.py。**

## 1. 背景与目标

现状(已勘察核实):

```text
PairedExperimentReport  ✓ 四格计数 + 逐题配对 + 因果语义(kind)
ProcessVerifier         ✓ #144 语义化过程判定(valid/violation/critical_veto)
AgentRunSummary         ✓ turns/tokens/cost/wall_time(无 tool_calls 计数)
```

缺口:评测产出止步于「描述性的配对报告」,没有把结果转成**可用于发布
门禁的明确结论**(IMPROVED / NEUTRAL / REGRESSED / BLOCKED)。

关键事实:
- `PairedExperimentReport.counts` 已有四格(fail→pass / pass→fail /
  pass→pass / fail→fail / invalid),可直接做 outcome 比较;
- `ProcessVerifier` 产出 `ProcessVerification`(含 status 与 violations),
  但目前**不落在 TaskResult 上**——比较层必须由调用方按
  `(task_id, attempt)` 提供两侧的 ProcessVerification(不扩执行链);
- `AgentRunSummary` 有 turns / input+output tokens / cost / wall_time,
  可直接聚合 efficiency;**没有 tool_calls 计数**,V1 不编造该指标;
- 小样本下统计显著性常无意义 → 门禁必须同时有「统计规则」与
  「确定性灾难规则」,不能把 `p < 0.05` 写成唯一通过条件。

目标:一个很小的决策层,消费 `PairedExperimentReport`(+ 可选的过程
校验结果),产出明确门禁结论,供 Harness 改动发布决策使用。

## 2. 需求

### 2.1 Outcome 比较(主判据)

- 消费四格,至少计算:

```text
净改善数 = fail→pass - pass→fail
delta_success_rate = 净改善数 / 有效配对数   (= candidate 成功率 - baseline 成功率)
```

- McNemar **exact test**(只取两个不一致格 b=fail→pass, c=pass→fail);
- 配对 bootstrap → delta_success_rate 的 95% 置信区间(确定性 seed);
- 两层判定规则:

```text
统计规则:McNemar p < alpha 且方向明确 → IMPROVED / REGRESSED
确定性灾难规则:胜方不一致格 >= min_discordant 且差 >= min_discordant
            → IMPROVED / REGRESSED(例:fail→pass=4, pass→fail=0 → IMPROVED)
```

### 2.2 Process 比较(直接消费 #144 的 ProcessVerifier 结果)

按 pair 比较 baseline / candidate 的 `ProcessVerification`:

```text
新增 critical veto(baseline 非 critical, candidate critical)→ BLOCKED 依据
新增 violation(baseline valid, candidate violation)
已有 violation 被消除(baseline 违规, candidate valid)
```

严重级顺序:VALID < VIOLATION < CRITICAL_VETO;EVIDENCE_UNAVAILABLE
视为不可比(该 pair 不计方向,只计入 unavailable)。

### 2.3 Efficiency guardrail(只观察,不作为主要优化目标)

- 指标:平均 turns / tokens / cost / wall time(**无 tool_calls,V1 缺数据**);
- 不写「工具调用更少 = 更好」;
- 规则:outcome 不退化、process 不退化的前提下,成本/耗时明显恶化才触发:

```text
cost +35% / wall time +40% 左右 → WARN
超过特别大阈值(如 +200%~+300%)→ BLOCKED
```

### 2.4 结果模型与门禁优先级(固定)

```python
class GateDecision(str, Enum):
    IMPROVED / NEUTRAL / REGRESSED / BLOCKED
```

优先级:

```text
1. 实验不可归因(UNSUPPORTED_TREATMENT)→ BLOCKED
2. 新增 critical process veto → BLOCKED
3. 明确 Outcome 回归 → REGRESSED
4. Outcome 改善且 Process 不退化 → IMPROVED
5. 其余 → NEUTRAL(效率 WARN 只记录;效率 BLOCKED 在 NEUTRAL 时升级为 BLOCKED)
```

## 3. 非目标

- 不扩执行链、不把 ProcessVerifier 接进 verified/orchestrator 落盘;
- 不做 regression_probe.py / first-error attribution / trajectory-prefix;
- 不新增 tool_calls 计数(数据源不在 TaskResult);
- 不做跨 run 的多次实验聚合。

## 4. 验收标准(6 个稳定判定用例)

```text
1. fail→pass=8, pass→fail=1, 无 process regression            → IMPROVED
2. fail→pass=1, pass→fail=6                                    → REGRESSED
3. Outcome 改善,但新增 test_tampering critical veto            → BLOCKED
4. Outcome 基本持平,Process 明显改善                            → NEUTRAL(可带 positive signal)
5. Outcome 持平,成本 +80%                                      → NEUTRAL/WARN
6. UNSUPPORTED_TREATMENT                                       → BLOCKED
```

## 5. 文件

```text
benchmarks/agent_e2e/comparison.py
benchmarks/agent_e2e/gate.py
tests/benchmarks/test_comparison.py
tests/benchmarks/test_gate_v2.py
```
