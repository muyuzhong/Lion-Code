# Implement: 受控实验语义(Controlled vs Regression 区分)

> 配套 `prd.md` / `design.md`。与证据投影并行(无依赖)。

## 0. 前置

- 分支:从 master(或 PR #143 合入后)新建 `eval-controlled-vs-regression`。
- 先读 `benchmarks/agent_e2e/experiment.py`(PR #143 现状)、
  `benchmarks/agent_e2e/agent_worker.py`(factory 调用点)、
  `lion_code/composition/full_product.py`(custom_system_prompt /
  tool_registry 签名)。

## 1. `benchmarks/agent_e2e/variant_injection.py`(新增)

- [ ] 1.1 `PromptVariantMap` / `ToolPolicyVariantMap` /
      `VariantInjectionSpec`(VersionedModel,含 fingerprint)。
- [ ] 1.2 `InjectionResolution`(custom_system_prompt /
      tool_registry / injection_fingerprint / resolved 布尔)。
- [ ] 1.3 `resolve_injection(profile, spec) -> InjectionResolution`:
      prompt/tool_policy 命中映射,未命中 → None + resolved=False;
      compression 永不注入。
- [ ] 1.4 单测:命中 / 未命中 / compression 不注入三类。

## 2. `benchmarks/agent_e2e/experiment.py`

- [ ] 2.1 `ExperimentKind` 枚举(controlled / regression)。
- [ ] 2.2 `build()` 判定 kind;CONTROLLED 校验「仅声明字段差异」
      (复用现有 invariants);REGRESSION 放宽 code_sha 不变量,
      其余不变量仍校验。
- [ ] 2.3 `PairedExperimentReport` 增 `experiment_kind` 字段 +
      `agent_code_sha`(两侧);validator:kind 与 sha 关系一致。
- [ ] 2.4 `render_markdown` 按 kind 输出结论措辞(design 3.4)。
- [ ] 2.5 单测:同 sha → controlled;跨 sha → regression;
      regression 下 catalog/seed 不同仍拒绝;report round-trip。

## 3. `benchmarks/agent_e2e/agent_worker.py`

- [ ] 3.1 `run_agent_worker` 增加 `injection_spec` 参数
      (默认 None = 现状零回归)。
- [ ] 3.2 factory 调用传入 custom_system_prompt / tool_registry
      (经 resolve_injection)。
- [ ] 3.3 单测:有 spec + 命中 → factory 收到注入;无 spec →
      默认行为(现有 test_agent_worker 全绿)。

## 4. spec 更新

- [ ] 4.1 `.trellis/spec/backend/agent-e2e-evaluation.md`:
      受控/回归语义契约;compression 声明字段定位(无运行开关,
      不可归因)。

## 5. 验证

- [ ] 5.1 `pytest tests/benchmarks/test_experiment_layer.py -q` 全绿。
- [ ] 5.2 `pytest tests/benchmarks/test_agent_worker.py -q`
      (环境性失败除外)。
- [ ] 5.3 `pytest tests/benchmarks -q` 全绿(环境性失败除外)。
- [ ] 5.4 ruff check 改动文件。

## 6. 提交

- [ ] 6.1 单次提交:
      `feat(benchmark): 受控/回归实验语义——PairedExperiment 区分 causation 与版本回归,worker 接通已有注入点`。