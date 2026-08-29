# Design: 受控实验语义(Controlled vs Regression 区分)

> 配套 `prd.md`。记录 ExperimentKind 判定、注入点接通与企业取舍。

## 1. 涉及面与边界

| 文件 | 动作 |
|---|---|
| `benchmarks/agent_e2e/experiment.py` | 修改:`ExperimentKind`;`PairedExperiment.build` 判定并校验;`PairedTrial`/`PairedExperimentReport` 记录 kind |
| `benchmarks/agent_e2e/agent_worker.py` | 修改:`run_agent_worker` 接通 custom_system_prompt / tool_registry 注入 |
| `benchmarks/agent_e2e/variant_injection.py` | **新增**:prompt/tool_policy 版本 → 运行时配置的受控映射表 + fingerprint |
| `benchmarks/agent_e2e/models.py` | **不改**(profile 已有 prompt_version / tool_policy_version / compression_version / agent_code_sha) |
| `tests/benchmarks/test_experiment_layer.py` | 扩展:kind 判定用例 |
| `.trellis/spec/backend/agent-e2e-evaluation.md` | 更新:受控/回归语义 + compression 声明字段定位 |

## 2. 数据流

```
PairedExperiment.build(baseline, candidate, declared_changes)
        │
        ├── agent_code_sha 相等?
        │     ├─ 是 → experiment_kind = CONTROLLED
        │     │      校验:除声明字段外无其他差异(既有 invariants)
        │     │      结论措辞:「机制导致」
        │     └─ 否 → experiment_kind = REGRESSION
        │              其余不变量仍须相同
        │              结论措辞:「版本整体回归」
        ▼
PairedExperimentReport(experiment_kind, agent_code_sha 两侧,
                       injection fingerprint)
```

worker 侧:
```
profile.prompt_version ──映射表──► custom_system_prompt
profile.tool_policy_version ──映射表──► tool_registry
profile.compression_version ──► 不注入(声明字段)
```

## 3. 具体设计

### 3.1 `ExperimentKind`

```python
class ExperimentKind(str, Enum):
    CONTROLLED = "controlled"
    REGRESSION = "regression"
```

- `build()` 判定:比较 `baseline.manifest.profile.agent_code_sha` 与
  candidate 侧。product 变更(非 profile 变量字段)而 code_sha 相同
  时仍为 CONTROLLED(由 agent_code_sha 的 git 语义保证,spec 记录
  该前提)。
- CONTROLLED 时沿用现有 invariants 全量校验(声明字段 == 实际差异);
  REGRESSION 时放宽「code_sha 不变量」,但 profile 的其余不变量与
  catalog/seed/budget 仍必须一致(否则 INVALID)。
- `PairedExperimentReport` 增加 `experiment_kind`;`render_markdown`
  按 kind 输出结论措辞。

### 3.2 注入映射(`variant_injection.py`)

```python
class PromptVariantMap(VersionedModel):
    prompt_version: str
    system_prompt: str            # 受控文本,评测侧维护
    fingerprint: str              # 内容指纹

class ToolPolicyVariantMap(VersionedModel):
    tool_policy_version: str
    tool_names: tuple[str, ...]   # 白名单;空 = 默认 registry
    fingerprint: str

class VariantInjectionSpec(VersionedModel):
    prompt_maps: tuple[PromptVariantMap, ...] = ()
    tool_policy_maps: tuple[ToolPolicyVariantMap, ...] = ()
    extensions: dict[str, Any] = {}
```

- `resolve_injection(profile, spec) -> InjectionResolution`:
  - prompt_version 命中 map → `custom_system_prompt`
  - tool_policy_version 命中 map → 构造对应 `ToolRegistry`
  - 未命中 → None(默认行为,与现状一致)
  - 返回 injection fingerprint(供报告记录)
- 映射表默认空(V1 不内置真实提示词资源);评测调用方按需提供。
  compression_version **永不**参与注入。

### 3.3 worker 接通

```python
async def run_agent_worker(request, *, agent_factory=..., 
                           trace_recorder=None, 
                           injection_spec: VariantInjectionSpec | None = None):
    ...
    injection = resolve_injection(request.manifest.profile, injection_spec or VariantInjectionSpec())
    agent = agent_factory(
        permission_mode=..., model=...,
        custom_system_prompt=injection.custom_system_prompt,  # None=默认
        tool_registry=injection.tool_registry,                # None=默认
        ...)
```

- `AgentExecutionRequest` 或 worker 入口增加 `injection_spec` 参数
  (选:manifest.extensions 透传不受污染,改为函数参数,由 harbor
  runner/调用方传入;实施时定)。
- 默认(无 spec)行为与现在完全一致——零回归。

### 3.4 报告与 spec

- Markdown:controlled → 「在 agent_code_sha=A、仅切换 {声明字段}
  下,机制导致的配对差异为…」;regression → 「版本 A→B 整体回归
  比较…(不归因具体机制)」;compression 提及「compression 暂为声明
  字段,无运行开关,不可归因」。
- spec `agent-e2e-evaluation.md` 补两条:受控/回归语义契约 +
  compression 声明字段定位。

## 4. 取舍

- **compression 不做真实开关**:跨核心边界(context manager
  compaction 配置化),单独立项;本轮如实标注防止误读 causation。
- **映射表默认空**:不内置 prompt 文本/工具清单,避免把资源内容
  塞进评测代码;调用方(真实评测)提供。映射表仍保证「声明改变
  真的被注入」的可审计性。
- **kind 判定只看 agent_code_sha**:profile 可变字段差异已由既有
  invariants 校验覆盖,不重复设计。

## 5. 验证命令

- `pytest tests/benchmarks/test_experiment_layer.py -q`
- `pytest tests/benchmarks/test_agent_worker.py -q`
- `pytest tests/benchmarks -q`