# Implement: 配对实验层(HarnessVariant / PairedExperiment / PairedTrial)

> 配套 `prd.md` / `design.md`。按序执行;每步完成即核对,进入下一步前
> 工作区干净(仅本任务改动)。

## 0. 前置

- 分支:从 master 新建 `eval-paired-experiment-layer`。
- 先读 `benchmarks/agent_e2e/models.py`(ExperimentProfile /
  EvaluationReport / TaskResult / ResultValidity / TaskVerdict /
  VersionedModel)与 `benchmarks/agent_e2e/regression.py`(`ChangeKind`),
  确认字段名与校验风格。

## 1. 新增 `benchmarks/agent_e2e/experiment.py`

- [ ] 1.1 `PairedTrialOutcome` 枚举(fail_to_pass / pass_to_fail /
      pass_to_pass / fail_to_fail / invalid)。
- [ ] 1.2 `HarnessVariant`:`variant_id` + prompt/compression/tool_policy
      三字段;`from_profile(profile, variant_id)`;`change_kinds(other)`
      返回实际不同字段对应的 `ChangeKind` 元组(从 models 导入
      `ChangeKind`?——实际 `ChangeKind` 定义在 `regression.py`,从
      `regression` 导入仅用于枚举值,不调用其函数)。
- [ ] 1.3 `PairedTrial`:`task_id` / `attempt` / `baseline_result` /
      `candidate_result` / `outcome_delta` + extensions;model_validator
      校验两侧结果存在且 INVALID 仅在任一侧非有效官方时出现。
- [ ] 1.4 `PairedCounts` + `PairedExperimentReport`(含 declared_changes /
      comparability_fingerprint / trials / counts / extensions);
      validator:counts 与 trials 映射一致。
- [ ] 1.5 `PairedExperiment.build(...)` 严格可比性校验(design 3.4 六步),
      失败抛 `PairedExperimentError(ValueError)` 带聚合中文错误;成功
      返回按 (task_id, attempt) 排序的 trials。
- [ ] 1.6 `_comparability_fingerprint(...)`(sha256,参照 regression 的
      `_digest` 风格:sort_keys + separators + default=str)。
- [ ] 1.7 `PairedExperimentReport.render_markdown()` 四格表中文摘要。
- [ ] 1.8 `__all__` 导出公共符号。

## 2. 新增 `tests/benchmarks/test_experiment_layer.py`

- [ ] 2.1 fixture:构造 baseline/candidate `EvaluationReport`(参考
      `tests/benchmarks/fixtures/verified_task_1.py` 与现有
      test_regression_feedback.py 的报告构造方式)。
- [ ] 2.2 HarnessVariant:提取正确、指纹稳定、change_kinds 正确。
- [ ] 2.3 outcome_delta 四格 + invalid 五类判定。
- [ ] 2.4 build 可比性:正常配对 / run_id 相同 / catalog 不同 /
      profile 不变量不同 / 声明变更与实际差异不符 / task 集合不一致 /
      attempt 错位 / 非 official 报告 → 各返回可读错误。
- [ ] 2.5 报告计数与手工四格一致;JSON round-trip。

## 3. 验证

- [ ] 3.1 `python -m pytest tests/benchmarks/test_experiment_layer.py -q`
      全绿。
- [ ] 3.2 `python -m pytest tests/benchmarks -q` 现有测试全绿。
- [ ] 3.3 `git diff --stat` 确认只动新增文件。

## 4. 提交

- [ ] 4.1 单次提交,message 如 `feat(benchmark): 配对实验层——Harness Variant 与 PairedExperiment 逐题配对`。

## 5. 后续钩子

- 子任务二(process-verifier)完成后,在 `PairedTrial.extensions` 挂接
  process 结果(若两边同时完成,合并评估是否在 extensions 上补
  `process` 字段——按顺序先合本任务,再由子任务二补)。
- 子任务三(comparison/gate V2)消费本报告做统计显著性与门禁。