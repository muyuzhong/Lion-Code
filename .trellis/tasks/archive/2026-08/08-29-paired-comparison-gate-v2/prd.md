# PRD: 配对统计与门禁 V2(comparison + 三重回归判定)

> 来源:父任务 `08-29-eval-harness-paired-system` PRD 3.4。
> **状态:后续阶段,仅 PRD(用户确认第一阶段为配对实验层 + 过程验证器,
> 本任务依赖两者产出的 PairedExperimentReport 与 ProcessVerification)。**

## 1. 背景与目标

paired samples 不是两个独立成功率:同一任务的两侧共享任务难度与模型
噪声,必须做配对分析。门禁结论必须基于「超过噪声的配对差异」,而不是
固定 10% 非劣界限加 3/3→0/3 灾难门禁。V2 门禁只保留三种判定,且
**目标指标与机制指标分离**:任务是否完成 / 过程是否安全正确是目标;
工具调用数、轮数、压缩次数是机制,机制变化不等于目标改善,不轻易
veto。

## 2. 需求

### 2.1 comparison.py(新模块)

- `fail_to_pass / pass_to_fail / pass_to_pass / fail_to_fail` 四格统计
  (消费 `PairedExperimentReport.trials`)。
- `paired_bootstrap`:在配对样本上重采样,给出目标量(如 pass→fail
  比率、delta)的置信区间;不依赖正态假设。
- `mcnemar`:配对 2×2 表上的假设检验,判断 fail→pass 与 pass→fail
  是否显著不对称(用户方案明确要求的配对检验)。
- 输出工程决策依据:「差异必须超过噪声」—— 显著性结论 + 效应量 + CI,
  而不是裸成功率。

### 2.2 Gate V2(重做 `regression.py` 的判定层)

保留三个判定类型,`regression.py` 从比较两个 EvaluationReport 改为
消费 PairedExperimentReport:

1. **Outcome Regression**:pass→fail 任务数 / fail→pass 任务数与
   McNemar/CI 结论;**主要阻止 merge**。
2. **Process Regression**:新增 critical_veto 数 /
   violation_rate 变化(两侧 `ProcessVerification` 对比);**主要阻止
   merge**;veto「改测试 / skip 验证」类行为)。
3. **Efficiency Regression**:机制指标(median tool calls、p95 turns,
   压缩次数等)变化 — 先作为 **observation**,不 veto。

- 策略模型沿用 V1 的严格版本化 `RegressionGatePolicy` 思想,但判定
  输入与语义升级;历史 V1 判定/账本兼容性按项目「零兼容包袱」原则
  处理(旧 gate 函数是否保留由实施时评审,倾向删除 V1 判定路径、
  保留账本读侧)。
- 声明变更契约(`ChangeKind` + 可比性校验)由配对实验层保证,gate
  不再重复实现。

### 2.3 报告

- PairedExperimentReport 增补显著性/McNemar/CI/gate 结论段;
- 中文摘要报告呈现四格 + 过程回归 + 效率观察,沿用现有报告风格。

## 3. 验收准则

- [ ] comparison.py 四格、bootstrap CI、McNemar 各自有单元测试
      (含已知答案的小样本用例,如手工 2×2 表)。
- [ ] Gate V2:outcome/process 回归触发 REJECT 的用例、pass 用例、
      efficiency 仅 observation 不 veto 的用例。
- [ ] regression.py 消费 PairedExperimentReport;旧「双 report 总
      成功率门禁」路径按评审删除或显式隔离。
- [ ] 报告含统计结论,可复核(seed 固定 / CI 方法标注)。
- [ ] 现有与配对相关的测试(第一、二子任务产出)全绿。

## 4. 非目标

- 不新增评分指标、不引入 LLM Judge;DeepEval 维持辅助诊断定位。
- 不改执行链;不改 `classify_failure` / 失败回流。
- 不做回归探针(子任务四)。
- 不实现 efficiency 的否决语义(保持 observation)。

## 5. 依赖

- `08-29-paired-experiment-layer` 的 `PairedExperimentReport`。
- `08-29-process-verifier` 的 `ProcessVerification`(挂接于
  PairedTrial.extensions)。