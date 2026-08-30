# Design: 配对实验层(HarnessVariant / PairedExperiment / PairedTrial)

> 配套 `prd.md`。本文件记录边界、数据流、具体改造与取舍;实施时以
> `implement.md` 的顺序清单执行。

## 1. 涉及面与边界

| 文件 | 动作 |
|---|---|
| `benchmarks/agent_e2e/experiment.py` | **新增**:`HarnessVariant` / `PairedTrial` / `PairedTrialOutcome` / `PairedExperiment` / `PairedExperimentReport` |
| `benchmarks/agent_e2e/report.py` | **不改**(仅当后续需要 Markdown 渲染时再评估;本轮不在 report.py 内扩展,PairedExperimentReport 自带独立渲染) |
| `benchmarks/agent_e2e/models.py` | **只读复用**,不新增字段 |
| `benchmarks/agent_e2e/regression.py` | **只读复用** `ChangeKind` 与 invariants 常量思想;不调用其私有函数,不修改 |
| `tests/benchmarks/test_experiment_layer.py` | **新增** 单元测试 |
| `benchmarks/agent_e2e/__init__.py` / `cli.py` | 不修改(本轮无 CLI 入口;配对报告由 API 驱动) |

边界原则:「纯新增模块 + 只读复用」,不触碰现有执行链与契约。

## 2. 数据流

```
baseline EvaluationReport ─┐
candidate EvaluationReport ─┤→ PairedExperiment.build(...)
declared_changes           ─┘        │
                          comparability 校验(失败→结构化错误)
                                     ▼
                        (task_id, attempt) 配对
                                     ▼
              PairedTrial{baseline_result, candidate_result,
                          outcome_delta} 序列
                                     ▼
                          PairedExperimentReport
                   (四格计数 + 摘要 + fingerprint)
```

## 3. 具体设计

### 3.1 `HarnessVariant`(models 风格 VersionedModel)

```python
class HarnessVariant(VersionedModel):
    variant_id: str                  # e.g. "baseline" / "candidate-v3"
    prompt_version: str
    compression_version: str
    tool_policy_version: str
    extensions: dict[str, Any] = {}

    @classmethod
    def from_profile(cls, profile: ExperimentProfile, variant_id: str) -> HarnessVariant
```

- 只承载三个可变字段;「不变量不属于可变面」由 `from_profile` 的显式
  字段清单保证(不引入通用 config 机制)。
- 指纹用现有 `VersionedModel.fingerprint()`。
- 提供 `change_kinds()` 帮助:与另一 variant 比较,返回实际不同的
  字段映射到 `ChangeKind`,供 PairedExperiment 校验「实际差异 ==
  声明变更」。

### 3.2 `PairedTrialOutcome` 枚举

```python
class PairedTrialOutcome(str, Enum):
    FAIL_TO_PASS = "fail_to_pass"
    PASS_TO_FAIL = "pass_to_fail"
    PASS_TO_PASS = "pass_to_pass"
    FAIL_TO_FAIL = "fail_to_fail"
    INVALID = "invalid"
```

### 3.3 `PairedTrial`

```python
class PairedTrial(VersionedModel):
    task_id: str
    attempt: int                     # seed 维度,现有 manifest repeats
    baseline_result: TaskResult
    candidate_result: TaskResult
    outcome_delta: PairedTrialOutcome
    extensions: dict[str, Any] = {}  # 预留 process_delta 的挂接点
```

判断规则:两侧都是 `official == True` 且 `validity == ResultValidity.VALID`
且 verdict ∈ {PASSED, FAILED} → 按四格映射;否则 `INVALID`。

### 3.4 `PairedExperiment`(构建器,不继承 VersionedModel 也不必)

```python
class PairedExperiment:
    def __init__(self, baseline, candidate, trials, declared_changes,
                 comparability_fingerprint): ...
    @classmethod
    def build(cls, baseline: EvaluationReport, candidate: EvaluationReport,
              declared_changes: Iterable[ChangeKind]) -> PairedExperiment
```

`build` 校验顺序(错误信息参照现有 `regression.py` 的 `_controlled_reason`
风格,聚合为一条可读消息):

1. 两 report 均为 `ReportStatus.OFFICIAL` 且 `official_score` 齐备
   (复用 `OfficialScore` 校验思路;不调用 regression 私有函数,build
   内实现轻量校验函数)。
2. run_id 不同;catalog lock(catalog_id / version / sha256 / task_ids /
   extensions)相同。
3. manifest 不变量字段相同(seed / repeats / timeout_seconds /
   budget_usd / platform / image digests / evaluator sha)。
4. profile 不变量字段相同(model / provider / thinking_level /
   permission_mode / seed / repeats / timeout_seconds / budget_usd /
   max_turns / credential_env_vars / extensions)。
5. 实际 profile 可变字段差异 == 声明变更集合(用 `ChangeKind` 映射);
   且至少有一个实际变更。
6. 两侧 `(task_id, attempt)` 集合完全一致;每条结果均有效官方。

### 3.5 `PairedExperimentReport`

```python
class PairedExperimentReport(VersionedModel):
    baseline_run_id: str
    candidate_run_id: str
    declared_changes: tuple[ChangeKind, ...]
    comparability_fingerprint: str          # 64 hex,复用现有 digest 风格
    trials: tuple[PairedTrial, ...]
    counts: PairedCounts                     # 内嵌 VersionedModel
    extensions: dict[str, Any] = {}

class PairedCounts(VersionedModel):
    fail_to_pass: int
    pass_to_fail: int
    pass_to_pass: int
    fail_to_fail: int
    invalid: int
```

- 校验:counts 之和 == len(trials),且每项计数与 trials 逐条映射一致
  (model_validator)。
- `render_markdown() -> str`:四格表 + 摘要(参考现有 report 中文风格)。

## 4. 取舍与理由

- **不引入 per-task seed**:manifest 契约是"manifest 级 seed + repeats",
  配对键用 attempt 即可表达"同一 seed 维度",零契约改动。
- **不在 report.py 扩展**:report.py 服务于单次 EvaluationReport 的
  JSON/中文渲染;配对报告是新的上层对象,自带渲染更内聚,避免耦合。
- **不调用 regression 私有函数**:`_comparability_errors` 等是私有实现;
  PairedExperiment 独立实现可比性校验(约 60 行),避免跨模块私有依赖,
  也避免触碰现有 gate 语义。若未来发现完全重复,再评估提取。
- **extensions 预留 process_delta**:子任务二随后用 extensions 挂接
  process 结果,不动本模块 schema(遵循 VersionedModel 扩展约定)。
- 校验是**严格拒绝式**(失败即返回结构化错误),不做 fallback 配对。

## 5. 验证命令

- 单元测试:`python -m pytest tests/benchmarks/test_experiment_layer.py -q`
- 回归:`python -m pytest tests/benchmarks -q`(确保现有评测测试不破)