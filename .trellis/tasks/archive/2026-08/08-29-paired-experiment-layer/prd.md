# PRD: 配对实验层(HarnessVariant / PairedExperiment / PairedTrial)

> 来源:父任务 `08-29-eval-harness-paired-system` PRD 3.2。
> 用户指定第一阶段实施内容:「PairedExperiment + ProcessVerifier」;
> 本任务为其中「实验层」部分,与 `08-29-process-verifier` 并发独立。
> 不修改现有执行链与报告契约。

## 1. 背景与目标

现在 regression gate 比较的是两个总成功率(`baseline success rate →
candidate success rate → 差多少`),加固定 V1 非劣界限。改造目标:把
「Harness 配置差异」变成评估的一等公民——同一 task、同一 attempt
(seed 维度)、同一 model/provider/budget,仅切换一个 Harness 变量,
逐题得到 paired delta,而不是只看聚合成功率。

## 2. 需求

### 2.1 `HarnessVariant`

- 描述一次实验中 Harness 的可变部分(prompt / compression /
  tool_policy,与现有 `ChangeKind` 对齐;retry/checkpoint 等为未来
  扩展,不在本轮字段集)。
- 从 `ExperimentProfile` 的可变字段派生(`prompt_version` /
  `compression_version` / `tool_policy_version`),携带 variant 标识
  (如 `baseline` / `candidate`)与稳定指纹。
- 构造时校验:model / provider / seed / repeats / budget / max_turns
  等不变量字段不属于 variant 的可变面(即 variant 只承载可变字段)。

### 2.2 `PairedExperiment`

- 输入:baseline `EvaluationReport` + candidate `EvaluationReport` +
  声明变更 `ChangeKind` 集合(与现有 gate 契约同源:`ExperimentManifest`
  冻结快照可比性)。
- 可比性校验复用现有 gate 的 invariants 思想:run_id 不同、catalog 锁
  相同、manifest/profile 不变量字段全同、实际 profile 差异 == 声明变更。
  校验失败时返回可读错误,不抛出半成品配对。
- 配对维度:`(task_id, attempt)`(attempt 即用户方案中的 seed 维度)。
  两个 report 必须覆盖完全相同的 `(task_id, attempt)` 集合。
- 输出:有序 `PairedTrial` 序列 + 配对统计视图。

### 2.3 `PairedTrial`

- 字段:`task_id`、`attempt`(seed 维度)、`baseline_result`、
  `candidate_result`(均为现有 `TaskResult`)、`outcome_delta`。
- `outcome_delta` 枚举:`FAIL_TO_PASS` / `PASS_TO_FAIL` /
  `PASS_TO_PASS` / `FAIL_TO_FAIL` / `INVALID`(任一侧结果非
  passed/failed 的有效官方结果时)。
- 仅在同一 attempt 的两侧都是 `official` 且 `validity == VALID` 时
  才算可比配对。

### 2.4 `PairedExperimentReport`

- 聚合:fail_to_pass / pass_to_fail / pass_to_pass / fail_to_fail /
  invalid 计数;不在此层做统计显著性(属于子任务三 comparison.py)。
- 含 manifest 快照比较摘要(baseline/candidate run_id、声明变更、
  comparability fingerprint)。
- 可序列化为 JSON(遵循现有 VersionedModel 严格契约)并可写中文
  Markdown 摘要报告。
- 保留每个 PairedTrial 的逐题明细,供后续 ProcessVerifier 挂接
  process_delta。

## 3. 验收准则

- [ ] `HarnessVariant.from_profile(profile, variant_id)` 正确提取三个
      可变字段并生成指纹;拒绝把不变量字段当作可变面。
- [ ] `PairedExperiment.build(baseline, candidate, declared_changes)`:
      可比时产出与两侧结果一一对应的 `PairedTrial` 列表;不可比时返回
      结构化错误(含具体不变量字段差异,参照现有 gate 错误风格)。
- [ ] outcome_delta 对四格 + invalid 五类全判定正确;单元测试覆盖
      (task×attempt 完全配对、部分配对、attempt 错位、invalid 注入)。
- [ ] `PairedExperimentReport` 计数与手工四格统计一致;JSON 可
      round-trip(`from_json` / `canonical_json`),报告含
      comparability fingerprint。
- [ ] 新增 `tests/benchmarks/test_experiment_layer.py`(或类似命名)
      覆盖上述行为;现有 tests/benchmarks 测试全部保持通过。
- [ ] 不修改 `backend.py` / `agent_worker.py` / `harness_runner.py` /
      `models.py` 中现有契约字段(纯新增模块与新增对 read-only 的复用)。

## 4. 非目标

- 不做统计显著性 / bootstrap / McNemar(子任务三)。
- 不做 ProcessVerifier 与 process_delta 挂接(子任务二,接口预留即可)。
- 不做新执行的自动编排(先支持已有报告离线配对)。
- 不引入 per-task seed 新机制(attempt 即 seed 维度)。
- 不改 `regression.py` 现有 gate(子任务三才重组)。