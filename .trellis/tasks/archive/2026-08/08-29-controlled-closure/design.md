# Design: Controlled Experiment Closure——让受控注入真正进入评测协议

> 配套 `prd.md`。记录链路打通、证据落盘、判定收紧与取舍。

## 1. 涉及面与边界

| 文件 | 动作 |
|---|---|
| `benchmarks/agent_e2e/variant_injection.py` | 扩展:`VariantInjectionResolution` 增加 requested/resolved 字段;`resolve_injection` 返回完整证据 |
| `benchmarks/agent_e2e/models.py` | `WorkerResult` 增加 `injection_evidence`(受控字段);`TaskResult.extensions` 复用(已有) |
| `benchmarks/agent_e2e/manifest` 相关(`models.py` ExperimentManifest) | manifest.extensions 携带 `variant_injection_spec`(extensions JSON 对象) |
| `benchmarks/agent_e2e/worker_entrypoint.py` | 从 manifest.extensions 读 spec → 传 `run_agent_worker(injection_spec=...)`;结果写 injection_evidence |
| `benchmarks/agent_e2e/harbor_agent.py` | `_SOURCE_FILES` 补 evidence.py / variant_injection.py |
| `benchmarks/agent_e2e/harbor_runner.py` | `HarborExecutionRequest` 增加 `injection_spec` 字段(可选);build_command 无需改(manifest_json 已含) |
| `benchmarks/agent_e2e/experiment.py` | `ExperimentKind` 增加 `UNSUPPORTED_TREATMENT`;`PairedExperiment.build` 收紧 CONTROLLED 判定;Report 校验 injection_fingerprint |
| `benchmarks/agent_e2e/orchestrator.py` | worker 结果 → TaskResult 透传 injection_evidence(读出即可,实施时确认落点) |
| `tests/benchmarks/*` | 新增/修订:注入证据、判定收紧、compression 禁入、source 清单 |
| `.trellis/spec/backend/agent-e2e-evaluation.md` | 同步受控判定契约 |

## 2. 数据流(目标态)

```
评测方(host)
  ├─ baseline manifest + VariantInjectionSpec{v1→promptA, v2→promptB}
  └─ candidate manifest + 同一 Spec(或各自 Spec)
         │
         ▼
harbor_runner → build_command(--agent-kwarg manifest_json=...) 
         │
         ▼
harbor_agent(LionInstalledAgent)  # _SOURCE_FILES 已含 evidence/variant_injection
  └─ request.json = {manifest(含 spec), task, attempt}
         │
         ▼
worker_entrypoint.main()
  ├─ spec = manifest.extensions["variant_injection_spec"]
  └─ run_agent_worker(request, injection_spec=spec)
         │
         ▼
agent_worker: resolve_injection(profile, spec)
  └─ injection_evidence = {
        requested_variant: {prompt_version, tool_policy_version},
        resolved_variant: {prompt_hit, tool_hit},
        injection_fingerprint: sha256(prompt文本 + 工具清单)
     }
  └─ WorkerResult.injection_evidence
         │
         ▼
orchestrator → TaskResult.extensions["injection_evidence"]
         │
         ▼
PairedExperiment.build(baseline, candidate):
  CONTROLLED 条件(全部满足):
    same code_sha
    + 仅声明差异
    + 两侧 injection_evidence.resolved
    + 两侧 fingerprint 非空且不同
    + declared_changes 不含 COMPRESSION
  否则 → REGRESSION / UNSUPPORTED_TREATMENT(如实措辞)
         │
         ▼
PairedExperimentReport(experiment_kind, injection_fingerprint 必填当受控)
```

## 3. 具体设计

### 3.1 Spec 进 manifest(不动 ExperimentManifest schema)

- `ExperimentManifest.extensions`(已有 `dict[str, Any]`)存
  `"variant_injection_spec": <VariantInjectionSpec.canonical_json object>`。
  - 理由:不动 frozen schema、不回破坏既有 fixture/报告读取;
    extensions 是显式扩展点,spec 有 fingerprint 可复核。
  - 注意:`extensions` 是可比性不变量之一(两侧必须相同)——受控实验
    中 baseline/candidate **共用同一 Spec 是预期**(映射表相同,应用
    到的 profile 版本不同)。
- `harbor_runner.HarborExecutionRequest` 增加
  `injection_spec: VariantInjectionSpec | None = None`;构造 manifest
  时若提供则写入 profile 关联的 extensions(实施时确认:可能由
  runner 调用方构造 manifest 时注入,无需 runner 写)。

### 3.2 注入证据模型(variant_injection.py)

```python
class RequestedVariant(VersionedModel):
    prompt_version: str | None = None
    tool_policy_version: str | None = None

class ResolvedVariant(VersionedModel):
    prompt_hit: bool = False
    tool_policy_hit: bool = False

class InjectionEvidence(VersionedModel):
    requested: RequestedVariant
    resolved: ResolvedVariant
    injection_fingerprint: str | None = None   # 非空 = 真的注入了
```

- `resolve_injection` 改为返回 `InjectionResolution`(含上述证据字段,
  保留 custom_system_prompt / tool_names 供 worker 使用)。
- `InjectionEvidence` 落 `WorkerResult.injection_evidence`(models.py
  新增字段,VersionedModel 引用)。

### 3.3 worker 链路

- `worker_entrypoint.py`:`spec = _spec_from_manifest(manifest)` →
  `run_agent_worker(request, trace_recorder=recorder, injection_spec=spec)`
  → 结果写 `result.model_copy(update={"injection_evidence": ...})`;
  实际上 agent_worker 可直接返回,entrypoint 聚合。
- `agent_worker.py`:`run_agent_worker` 构造
  `InjectionEvidence` 进 `WorkerResult`(新增字段)。
- `harbor_agent.py`:`_SOURCE_FILES += ("evidence.py",
  "variant_injection.py")`。

### 3.4 判定收紧(experiment.py)

```python
class ExperimentKind(str, Enum):
    CONTROLLED = "controlled"
    REGRESSION = "regression"
    UNSUPPORTED_TREATMENT = "unsupported_treatment"   # NEW
```

- `_experiment_kind(baseline, candidate, declared_changes)` 逻辑:
  1. declared_changes 含 COMPRESSION → 永不 CONTROLLED
     (compression 无开关;同 code → UNSUPPORTED_TREATMENT /
      跨 code → REGRESSION);
  2. code_sha 不同 → REGRESSION;
  3. code 相同 + 仅声明差异:
     - 两侧 injection_evidence 齐全、resolved、fingerprint 非空且
       不同 → CONTROLLED;
     - 否则 → UNSUPPORTED_TREATMENT(如实措辞「声明变量无真实
       treatment,不可归因」)。
- `PairedExperiment.build` 读两侧 TaskResult.extensions 的
  `injection_evidence`(缺省视为未注入 → 不产生 CONTROLLED)。
- Report validator:`experiment_kind == CONTROLLED` 时
  `injection_fingerprint` 必填非空。

### 3.5 报告措辞

- CONTROLLED:「两侧 agent 代码相同且 injection 已生效(treatment
  已验证),配对差异可归因于声明变更的机制效果」。
- UNSUPPORTED_TREATMENT:「同代码但声明变量未注入/未解析,
  配对差异**不可**归因于该机制」。
- REGRESSION:维持「版本整体回归」。

## 4. 取舍

- **spec 走 manifest.extensions 而非新增 schema 字段**:零 schema
  漂移、既有 manifest 兼容;可比性校验中 extensions 相同正好保证
  「同一映射表」。
- **证据落 WorkerResult 新字段而非塞 extensions**:WorkerResult 已有
  严格 schema,新字段可模型校验、可序列化复核。
- **ExperimentKind 新增 UNSUPPORTED_TREATMENT 而非扩文言**:机器可判、
  报告/未来 Gate 可消费;避免把「无法归因」假装成 REGRESSION。
- **compression 禁入受控用 declared_changes 硬校验**:不依赖注入
  证据(本来就没有),规则简单可测。

## 5. 验证命令

- `pytest tests/benchmarks/test_variant_injection.py -q`
- `pytest tests/benchmarks/test_experiment_layer.py -q`
- `pytest tests/benchmarks/test_agent_worker.py -q`(环境性失败除外)
- 新增 `test_controlled_closure.py`(判定收紧 + 证据 + source 清单)
- `pytest tests/benchmarks -q`;ruff check + format --check