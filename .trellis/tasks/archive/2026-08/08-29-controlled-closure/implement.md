# Implement: Controlled Experiment Closure——让受控注入真正进入评测协议

> 配套 `prd.md` / `design.md`。按序执行;每步完成即核对。

## 0. 前置

- 分支:从 `master`(含 #143+#144)新建 `controlled-closure`。
- 先读:`variant_injection.py`(现有 resolve_injection)、
  `worker_entrypoint.py` / `harbor_agent.py`(`_SOURCE_FILES`)、
  `harbor_runner.py`(HarborExecutionRequest)、`experiment.py`(
  ExperimentKind/build/Report)、`models.py`(WorkerResult/TaskResult)。

## 1. 注入证据模型(variant_injection.py)

- [ ] 1.1 `RequestedVariant` / `ResolvedVariant` / `InjectionEvidence`
      (VersionedModel,design 3.2)。
- [ ] 1.2 `resolve_injection` 返回含证据的 `InjectionResolution`
      (requested/resolved/fingerprint);保留 custom_system_prompt /
      tool_names / 现有字段。
- [ ] 1.3 单测:命中/未命中/fingerprint 稳定。

## 2. Manifest 携带 Spec + worker 链路打通

- [ ] 2.1 `ExperimentManifest.extensions["variant_injection_spec"]`
      支持写入/读取(helper `attach_injection_spec(manifest, spec)` /
      `spec_from_manifest(manifest)` 放 variant_injection.py)。
- [ ] 2.2 `worker_entrypoint.py`:`spec_from_manifest(manifest)` →
      `run_agent_worker(..., injection_spec=spec)`。
- [ ] 2.3 `models.py` `WorkerResult` 增加
      `injection_evidence: InjectionEvidence | None = None`
      (VersionedModel 引用,严格序列化)。
- [ ] 2.4 `agent_worker.py`:`run_agent_worker` 构造 InjectionEvidence
      落入 WorkerResult;`harbor_agent.py` `_SOURCE_FILES` 补
      evidence.py / variant_injection.py。
- [ ] 2.5 `harbor_runner.py` `HarborExecutionRequest` 增加
      `injection_spec` 字段(可选,manifest 构造侧注入 extensions)。
- [ ] 2.6 测试:manifest 携带/读取 spec round-trip;worker 收到
      spec 且结果含证据;`_SOURCE_FILES` 清单断言(含两新模块)。

## 3. 判定收紧(experiment.py)

- [ ] 3.1 `ExperimentKind` 增加 `UNSUPPORTED_TREATMENT`。
- [ ] 3.2 `_experiment_kind` 重写(design 3.4):compression 硬禁受控;
      两侧 injection 证据校验(需求 2.3 全条件)。
- [ ] 3.3 `PairedExperiment.build` 从两侧 TaskResult.extensions 读
      injection_evidence;`to_report` 透传两侧 fingerprint。
- [ ] 3.4 Report validator:CONTROLLED 时 injection_fingerprint 必填。
- [ ] 3.5 render_markdown 三态措辞(design 3.5)。
- [ ] 3.6 测试:compression 同行 code → 不 CONTROLLED;未注入 /
      fingerprint 相同 → UNSUPPORTED_TREATMENT;全条件满足 →
      CONTROLLED;Report validator 拒绝受控无指纹。

## 4. spec 更新

- [ ] 4.1 `.trellis/spec/backend/agent-e2e-evaluation.md`:受控判定需
      injection 证据;compression 禁入受控;UNSUPPORTED_TREATMENT
      语义。

## 5. 验证

- [ ] 5.1 `pytest tests/benchmarks/test_controlled_closure.py -q` 全绿。
- [ ] 5.2 `pytest tests/benchmarks -q` 全绿(环境性失败除外)。
- [ ] 5.3 ruff check + `ruff format --check` 相关文件。

## 6. 提交

- [ ] 6.1 单次提交(或按层 2 个:链路打通 / 判定收紧):
      `feat(benchmark): Controlled Experiment Closure——注入进协议、证据落盘、受控判定收紧`。