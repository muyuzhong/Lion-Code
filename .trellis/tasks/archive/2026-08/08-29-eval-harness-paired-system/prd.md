# PRD: 评估体系收敛为 Harness 配对实验系统

> 来源:用户提案(Lion Code 评估体系下一阶段方向,第七章 Agent 评估收敛)。
> 核心转变:评估的中心问题从「这个版本的 Agent 得了多少分」改为
> 「这个 Harness 改动是否因果地改善了 Agent,以及改善/破坏发生在哪里」。
> 评估的最小单位从「一个 Agent 跑一道题得 0/1」改为
> 「一个 Harness 改动在同一冻结任务上的配对因果差异」。

## 1. 背景与目标

现有评估基础设施(任务冻结、隔离执行、官方 verifier、holdout、外部
SWE-bench 锚点、失败回流、DeepEval/Opik)已解决「评估结果可信吗」,
无需继续扩张。本轮改造把判断力聚焦到「Harness 改动本身」:

1. **配对实验**:同一 task × seed(现有模型为 attempt),同一 model /
   provider / budget / 环境,仅切换一个 Harness 变量(baseline vs
   candidate),得到逐题 paired delta(fail→pass / pass→fail),而非
   只比较两个总成功率。
2. **过程与结果分离**:官方 verifier 继续回答「代码最终对不对」
   (Outcome);新增确定性 ProcessVerifier 回答「Agent 是怎么做到的」
   (valid / violation / critical_veto),对**每条轨迹**运行,包括 PASS。
3. **按 Harness 故障面组织回归**:失败回流从「完整失败任务」逐步进化
   为「最小 bad case / trajectory prefix」,形成 Harness Regression
   Corpus,与 E2E Corpus 分层。

明确不做:不新增 Benchmark、Judge 或评分指标;DeepEval/Opik 保持现有
辅助诊断定位,不再扩张;不重写执行链(backend / agent_worker /
harness_runner / external_anchor / corpus / trace 全部复用)。

## 2. 任务地图

| 子任务 | 交付物 | 依赖 |
|---|---|---|
| `08-29-paired-experiment-layer` | `experiment.py`:HarnessVariant / PairedExperiment / PairedTrial + 配对报告 | 无(第一阶段) |
| `08-29-process-verifier` | `process_verifier.py`:ProcessVerifier / ProcessViolation,确定性轨迹规则,全轨迹运行 | 无(第一阶段,与配对层并发) |
| `08-29-paired-comparison-gate-v2` | `comparison.py`:fail_to_pass / pass_to_fail / paired_bootstrap / mcnemar;`regression.py` 改为消费 PairedExperimentReport;Gate V2 三重判定(outcome / process / efficiency) | 配对层 + 过程验证器 |
| `08-29-regression-probes` | `regression_probe.py`:TrajectoryPrefixCase / minimize_failure;Harness Regression Corpus 分层 | 过程验证器(首错归因) |

## 3. 需求

### 3.1 评估对象:Harness Variant(全局)

- 一次正式实验只比较 Baseline Harness vs Candidate Harness;model、
  provider、任务、seed、budget、环境全部锁死,只有声明变更的字段不同。
- `HarnessVariant` 描述 Harness 的全部可变部分(prompt / compression /
  tool_policy,后续可扩 retry / checkpoint),可独立开关,从
  `ExperimentProfile` 的可变字段派生并生成指纹。
- 任何 Lion Code 架构改动必须能回答「这次改变了哪个变量」。

### 3.2 配对实验(第一阶段子任务一)

- 单个 `EvaluationReport` 不再是比较单位;新增 `PairedExperiment` 上层
  对象,消费两次现有报告(baseline + candidate),按 `(task_id, attempt)`
  配对出 `PairedTrial` 序列。
- `PairedTrial` 记录:task_id、seed/attempt、baseline_result、
  candidate_result、outcome_delta、process_delta。
- 配对报告关注 fail→pass / pass→fail / pass→pass / fail→fail 四格,
  而不是两个总成功率。
- 底层仍调用现有 Agent.run()、container backend 与官方 verifier。

### 3.3 过程验证器(第一阶段子任务二)

- 新增 `ProcessVerifier`,**对每条轨迹**(含 PASS)运行,消费已有 typed
  `TraceEvent`(已脱敏,host 侧接入点:`artifacts/harbor-trace.json`)。
- V1 只做确定性规则,不引入 LLM Judge:
  - `repeated_tool_call`:相同工具 + 相同参数连续重复 ≥ N 次
  - `tool_error_not_recovered`:工具失败后 Agent 未改变策略持续重复
  - `validation_missing`:声称完成,但轨迹缺失任务卡要求的验证行为
    (依据 `TaskSpec.public_validation_commands`)
  - `test_tampering`:修改 verifier / test / skip 等受保护区域
  - `premature_termination`:未满足任务目标即主动结束
  - `context_regression`:compaction 后首次行为违反压缩前仍存在的关键约束
- 产出二维结果:`outcome: passed/failed` × `process: valid /
  violation / critical_veto`。veto(如改测试/skip 验证)为 critical。
- 与现有 `classify_failure()` 并存:classify_failure 及其 triage/回流
  链保持现状不动;ProcessVerifier 是独立的新判定层(用户已确认)。

### 3.4 配对统计与门禁 V2(后续阶段子任务三)

- `comparison.py`:fail_to_pass / pass_to_fail 四格统计;配对样本上的
  bootstrap 置信区间与 McNemar 检验;差异必须超过噪声才能作为工程依据。
- Gate V2 只保留三种判定:Outcome Regression(主要阻止 merge)、
  Process Regression(主要阻止 merge)、Efficiency Regression(先作为
  observation,不轻易 veto;机制指标变化不等于目标改善)。
- `regression.py` 从比较两个 EvaluationReport 改为消费
  PairedExperimentReport。

### 3.5 回归探针(后续阶段子任务四)

- 保留「失败 → classify → 人工 triage → regression corpus」链路。
- 新增 failure minimization:从轨迹中定位**第一个使轨迹偏离正确路径的
  错误**,截取 trajectory prefix(1..k)+ 当前环境状态 + 可接受/禁止
  动作,生成最小 `TrajectoryPrefixCase`,而不是每次保存完整大型任务。
- 数据集分两层:E2E Corpus(整体能不能做成)+ Harness Regression
  Corpus(这个 Harness bug 有没有修好)。

## 4. 验收准则(全局)

- [ ] `benchmarks/agent_e2e/experiment.py` 与 `process_verifier.py`
      存在且独立可测(第一阶段两个子任务的验收见各自 PRD)。
- [ ] 一次配对实验的产物能回答:「仅开启某 Harness 变量,哪些任务
      fail→pass、哪些 pass→fail、过程代价是什么」。
- [ ] 每条轨迹(含 PASS)都产出 process 状态,能在报告上呈现
      PASS+violation 这类「做成了但 Harness 行为有问题」的案例。
- [ ] 现有执行链、官方 verifier 判定、classify_failure 回流链路零改动。
- [ ] 报告可复核:配对报告含 baseline/candidate 的 run_id、声明变更、
      comparability fingerprint(复用/对齐现有 V1 契约思想)。

## 5. 非目标(No-go)

- 不新增 Benchmark 任务、LLM Judge 或评分指标;DeepEval 保持辅助
  诊断工具定位,不向评分体系发展。
- 不重写 backend / agent_worker / harness_runner / external_anchor /
  corpus / trace 的执行与落盘链路。
- 不修改现有 `classify_failure()` 的规则与 `FailureRecord` 契约
  (两个系统并存,后续再评估统一)。

## 6. 风险与开放问题

- 配对执行成本翻倍:同一 task × attempt 需跑两次;先支持「已有报告
  配对」(离线配对已有产物),新执行的自动化编排后续再补。
- ProcessVerifier 规则的误报/漏报用确定性规则 + 单元测试锁定,人工
  可审计;`test_tampering` 的「受保护区域」判定需明确边界(verifier /
  test / skip 相关工具调用模式),V1 宁严勿松、记录不自动否决。
- 配对的「同一 attempt = 同一 seed」仅在现有 manifest 契约下成立
  (manifest 级 seed + repeats),不引入 per-task seed 新机制。