# Design:评测链 PR C(评分语义化)

> 配套 `prd.md`。本文件记录边界、数据流、具体改造与取舍;实施时以
> `implement.md` 的顺序清单执行。

## 1. 涉及面与边界

| 文件 | 动作 |
|---|---|
| `benchmarks/agent_e2e/models.py` | `DeepEvalMetricResult` +threshold/threshold_met;新 `DeepEvalScoreGate`;`DeepEvalAnalysis` +agent_model/judge_fingerprint/score_gate |
| `benchmarks/agent_e2e/deepeval_analysis.py` | 阈值常量;观察→结果阈值填充;fixture 解析按名补齐;analyze_* 透传 agent_model/judge_fingerprint;score_gate 计算 |
| `benchmarks/agent_e2e/deepeval_metrics.py` | `build_deepeval_metrics` 以阈值常量构造 SDK metric |
| `benchmarks/agent_e2e/verified_runner.py` | 计算 judge 指纹;分析入口传 agent_model/judge_fingerprint;`_analysis_failure` 透传 |
| `benchmarks/agent_e2e/report.py` | DeepEval 段渲染 Agent/Judge 模型与指纹、阈值对照、门禁结论;Harbor/Harness 分歧标注 |
| `scripts/benchmarks/verified-smoke/run_smoke.sh` | 必填 `DEEPEVAL_JUDGE_MODEL`;传 `--deepeval-judge-model` |
| `scripts/benchmarks/verified-smoke/smoke.env.example` | +`DEEPEVAL_JUDGE_MODEL` 变量名与注释 |
| `scripts/benchmarks/verified-smoke/README.md` | env 表 + judge 独立说明 |
| `docs/agent-e2e-verified-run.md` | judge 独立配置与指纹、评分阈值与门禁、分歧标注三小节 |
| `tests/benchmarks/*` | 上述四个测试文件增补/调整 |

不触碰:CLI 退出码语义(`verified_exit_code`)、`task_result` 判定链、
`DeepEvalResultFixture` 输入 schema、Harbor/Harness/Opik 阶段。

## 2. 数据模型(models.py)

### 2.1 DeepEvalMetricResult(新增两个可选字段)

```python
threshold: float | None = Field(default=None, ge=0, le=1)
threshold_met: bool | None = None
```

validator 扩展:`threshold` 与 `threshold_met` 必须同存同缺(成对);
两者齐备时 `threshold_met == (status is COMPLETED and score is not None
and score >= threshold)`——failed/timeout 指标(score 恒 None)恒为
False,completed 且有分数才可能 True。

### 2.2 DeepEvalScoreGate(新模型,单用途小结构)

```python
class DeepEvalScoreGate(VersionedModel):
    """单次分析的 judge 阈值对照结论;只作观测,不改变确定性判定。"""
    passed: bool
    passed_metrics: int = Field(ge=0)
    evaluated_metrics: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=320)
```

validator:passed_metrics ≤ evaluated_metrics;evaluated_metrics ≥ 1;
`passed == (passed_metrics == evaluated_metrics)`。

### 2.3 DeepEvalAnalysis(新增三个可选字段)

```python
agent_model: str | None = Field(default=None, max_length=256)
judge_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
score_gate: DeepEvalScoreGate | None = None
```

- `agent_model`= 运行期 `manifest.profile.model`(fixture 解析路径无此
  信息 → None)。
- `judge_fingerprint`= SHA-256 hex,内容 `"{judge_model}\n{endpoint}"`,
  endpoint 取环境 `LITELLM_API_BASE`(未设为空串)。端点只进指纹,不
  进报告原文(脱敏红线)。
- 全部带默认值 → 旧 JSON 报告可继续 `model_validate`(additive,
  `extra="forbid"` 只禁未知键),SCHEMA_VERSION 保持 `agent-e2e/v1`。

## 3. 分析组合(deepeval_analysis.py)

### 3.1 阈值常量

```python
DEEPEVAL_METRIC_THRESHOLDS: Mapping[str, float] = {
    "TaskCompletionMetric": 0.5,
    "StepEfficiencyMetric": 0.5,
    "TrajectoryQuality": 0.5,
}
```

统一 0.5 的理由:中点判定,简单可解释,三指标同语义;文档写明为运行
侧策略常量,后续可按需演进(演进=改常量,不引配置系统)。

### 3.2 观察 → 结果(唯一填充点)

`_metric_result_from_observation` 在算出 status/score 后:

```python
threshold = DEEPEVAL_METRIC_THRESHOLDS.get(metric_name)
threshold_met = (
    None
    if threshold is None
    else status is AdapterStatus.COMPLETED
    and score is not None
    and float(score) >= threshold
)
```

### 3.3 fixture 解析路径(parse_deepeval_analysis)

指标循环内按 `metric.name` 从常量取 threshold 并计算 threshold_met
(规则同 3.2)。`DeepEvalResultFixture` 输入 schema 不动——阈值是宿主侧
策略,不属输入内容;fixture 无 score 时(非 completed)threshold_met=False。

### 3.4 score_gate 计算(唯一填充点:_analysis_from_metrics)

```python
scored = tuple(
    m for m in metrics
    if m.status is AdapterStatus.COMPLETED and m.threshold is not None
)
score_gate = None
if scored:
    passed_metrics = sum(1 for m in scored if m.threshold_met is True)
    score_gate = DeepEvalScoreGate(
        passed=passed_metrics == len(scored),
        passed_metrics=passed_metrics,
        evaluated_metrics=len(scored),
        reason=(
            f"全部 {len(scored)} 项已评分指标达阈值(阈值 0.5)"
            if passed_metrics == len(scored)
            else f"{len(scored)} 项已评分指标中 {passed_metrics} 项达阈值(阈值 0.5)"
        ),
    )
```

无已评分指标(全失败/超时/不可用)→ None(报告渲染为"无已评分指标")。
reason 中阈值用 `DEEPEVAL_METRIC_THRESHOLDS` 实际值拼接;message 受控、
无原始正文。

### 3.5 分析入口透传

`analyze_deepeval_case(..., agent_model: str | None = None,
judge_fingerprint: str | None = None)` 与
`analyze_verified_report(...)` 同签名扩展;`_analysis_from_metrics` /
`_unavailable_analysis` 一并透传。默认 None 保持既有调用方兼容。
`_ensure_telemetry_off` 等安全入口不动。

## 4. runner(verified_runner.py)

`_run_post_processing` 中:

```python
judge_model = request.deepeval_judge_model or request.manifest.profile.model
agent_model = request.manifest.profile.model
judge_fingerprint = _judge_fingerprint(judge_model)  # 见下
```

`_judge_fingerprint(model)`:

```python
endpoint = os.environ.get("LITELLM_API_BASE") or ""
return hashlib.sha256(f"{model}\n{endpoint}".encode()).hexdigest()
```

`_analysis_failure` 增加 agent_model/judge_fingerprint 参数并写入结果
(失败分析也保留运行期身份,便于追溯)。CLI/退出码零改动。

## 5. 模板与文档(P1-3 运维侧)

- `run_smoke.sh`:必填循环追加 `DEEPEVAL_JUDGE_MODEL`(排在末尾,既有
  "未填写 LION_MODEL" 测试不受影响);verified-run 调用追加
  `--deepeval-judge-model "$DEEPEVAL_JUDGE_MODEL"`;头部注释与
  check-only 提示同步更新。
- `smoke.env.example`:新增分组"DeepEval judge 模型(必填,独立于 agent
  模型)",注册 `DEEPEVAL_JUDGE_MODEL`,附说明。
- `README.md`:env 表新增 `DEEPEVAL_JUDGE_MODEL`(✅),说明固定 judge
  避免 agent 换代致分数不可比、报告记录模型与指纹。
- `docs/agent-e2e-verified-run.md` 增补三个小节(见 §7)。

## 6. 报告渲染(report.py)

### 6.1 DeepEval 段扩展

```
- DeepEval:状态 `completed`;Agent 模型:`{agent_model}`;Judge 模型:
  `{judge_model}`;Judge 指纹:`{judge_fingerprint}`;输入 digest:...
  - TaskCompletionMetric:0.0000(阈值 0.5000,未达);状态 `completed`;
    原因:...
```

- 指标行:分数后追加 `(阈值 {threshold:.4f},{达|未达})`(threshold 为
  None 时不追加)。
- 模型行:Agent 模型缺省显示"未记录"(fixture 解析路径)。
- 指纹:完整 64 hex 展示(非敏感)。

### 6.2 门禁结论行(DeepEval 段末尾)

```
- 门禁结论:确定性判定 = passed(官方 Harness);judge 评分门禁:
  通过(3/3 达阈值;观测,不参与判定)
```

- 确定性侧:`task_result.official` True → `确定性判定 = <verdict>
  (官方 Harness)`;False → `确定性判定 = <verdict>(无官方结果)`。
- 门禁侧:score_gate None → `judge 评分门禁:无已评分指标`;否则
  `通过/未达({passed_metrics}/{evaluated_metrics} 达阈值;观测,不参与判定)`。

### 6.3 分歧标注(P2-1)

渲染 harness 段后调用 `_harbor_harness_divergence(report)`:

```python
def _harbor_harness_divergence(report) -> str | None:
    harbor, harness = report.harbor, report.harness
    if harbor is None or harness is None: return None
    if harbor.status is not AdapterStatus.COMPLETED: return None
    if harness.status is not AdapterStatus.COMPLETED: return None
    if harbor.verifier_outcome is VerifierOutcome.FAILED and harness.resolved:
        return ("Harbor 例行 verifier 判失败(reward {reward:.4f})而官方 Harness "
                "resolved=true:判定以官方 Harness 为准,Harbor 侧仅过程证据,"
                "reward 不参与判定")
    if harbor.verifier_outcome is VerifierOutcome.PASSED and harness.resolved is False:
        return ("Harbor 例行 verifier 判通过而官方 Harness 未通过:"
                "判定以官方 Harness 为准")
    return None
```

md 渲染为固定前缀行:`- 分歧标注:<text>`。JSON 不加字段(分歧可由
harbor/harness 两段推导,标注为展示层语义),文档注明。reward 只进
文字不进 JSON 判定(不变量不变)。

## 7. 文档增补(docs/agent-e2e-verified-run.md)

在"DeepEval judge 端点"小节之后新增:

- **judge 独立配置与指纹**:`--deepeval-judge-model`(直接 CLI 可选,
  未传默认跟随 agent 模型);一键脚本必填 `DEEPEVAL_JUDGE_MODEL` 并显式
  传递;报告同时记录 agent 模型、judge 模型与 Judge 指纹(SHA-256 于
  judge 模型 + LITELLM_API_BASE);agent 换代不再静默改变评分基准。
- **评分阈值与门禁语义**:三指标阈值 0.5(运行侧策略常量);报告含
  逐项阈值对照(`threshold`/`threshold_met`)与 `score_gate` 门禁结论;
  确定性判定(官方 Harness)权威,judge 评分与 Harbor reward 均为观测、
  不参与判定;CLI 退出码约定不受分数影响。
- **Harbor 与官方结果分歧**:例行 verifier 与官方 Harness 结论冲突时
  md 渲染明确失败归属文字(以官方 Harness 为准);JSON 保留两段原始
  字段可推导。

## 8. 测试设计

| 文件 | 增补/调整 |
|---|---|
| `test_eval_analysis_observability.py` | 全过(fake 0.75)→ threshold/threshold_met/score_gate(3/3)断言;部分低于阈值 → passed=False、逐项 threshold_met;全超时 → score_gate None;partial(一指标异常)→ 失败指标 threshold_met=False;analyze_verified_report 记录 agent_model/judge_fingerprint |
| `test_verified_contracts.py` | 模型 validator:threshold 与 threshold_met 必须成对、不一致拒绝;score_gate passed 与计数不一致拒绝;fixture 解析按常量补齐阈值 |
| `test_verified_cli_composition.py` | md 含 "Agent 模型"/"Judge 指纹"/"门禁结论";分歧场景(harness resolved + harbor failed)含 "分歧标注";一致场景无标注 |
| `test_smoke_template_guard.py` | ENV_FILE_CONTENT 增 DEEPEVAL_JUDGE_MODEL;新用例:缺该变量 → rc=2 且提示变量名 |

## 9. 取舍记录

- **阈值固定常量 vs 可配置**:常量 + 文档,不引配置系统;演进只改
  常量与文档(防过度设计)。
- **score_gate 进 analysis vs 新建顶层字段**:门禁属于分析语义,就近
  挂在 `DeepEvalAnalysis.score_gate`;报告根对象不加字段。
- **分歧标注只进 md**:JSON 是原始字段的严格容器,展示层语义由 md
  承担;验收判据就是报告文字,不引入重复的派生字段。
- **不做 Harbor verifier 重试**:重试改变 runner 行为且不解决"失败
  归属"问题;标注文字已满足验收(prd.md 非目标已记录)。
- **CLI 默认跟随保留 + 模板必填**:直接 CLI 保持向后行为(显式参数
  可用),一键脚本(运维路径)强制显式固定,静默跟随只在用户跳过模板
  时可能且已由报告双模型字段显式暴露。
- **端点指纹脱敏**:endpoint 只进 sha256,原值不落盘(与既有
  redact_text 边界一致)。

## 10. 完成判定(与 prd.md A1–A5 对应)

- A1:`DeepEvalAnalysis` 三字段存在且 md 展示(单测断言)。
- A2:模板三文件同步更新;缺 `DEEPEVAL_JUDGE_MODEL` rc=2(子进程测试);
  run_smoke.sh 传 `--deepeval-judge-model`。
- A3:阈值/门禁四种语义用例全绿;旧 fixture 补齐阈值。
- A4:分歧/一致渲染用例 + A5 实际报告复核。
- A5:targeted 测试 + `git diff --check` + 单元回归;本机复跑闭环
  (DEEPEVAL_JUDGE_MODEL 显式),报告呈现新字段;backlog 勾销。