# Design: DeepEval 安全语义工具轨迹

## 1. Boundary

```text
typed Core events (single Agent run)
        |
        +--> existing TraceRecorder --> harbor-trace.json (unchanged)
        |
        +--> AnalysisTrace projector --> analysis-trace.json
                                           |
                                           +--> DeepEval
                                                 +-- ArgumentCorrectness
                                                 +-- ToolDecisionQuality
                                           |
                                           +--> existing report rendering

official Harness ------------------------------> TaskResult.verdict (unchanged)
ProcessEvidence -------------------------------> ProcessVerifier (unchanged)
existing observability payload ----------------> Opik (unchanged)
```

`AnalysisTrace` 是 DeepEval 的窄输入适配物，不是新的全局诊断模型。它不成为 ProcessVerifier、Opik 或 Lion Runtime 的共同抽象。

## 2. Minimal Data Contract

新增 `benchmarks/agent_e2e/analysis_trace.py`，在同一文件内放置最小 schema、投影和加载校验，不增加 registry、adapter hierarchy 或跨模块 wire-model 迁移。

```python
class AnalysisTraceEvent(VersionedModel):
    sequence: int
    kind: Literal["tool_call", "tool_result"]
    tool_call_id: str
    tool_name: str
    action: str
    safe_data: dict[str, JSONValue]

class AnalysisTrace(VersionedModel):
    task_id: str
    trace_id: str
    events: tuple[AnalysisTraceEvent, ...]
    event_count: int
    truncated: bool
    trace_digest: str
```

实现时允许按现有基类命名微调字段，但不能再拆出 `AnalysisToolCall`、`AnalysisToolResult`、`AnalysisDecision` 或 diagnosis/finding 模型。事件按原始 `sequence` 排序，call/result 只通过 `tool_call_id` 关联；DeepEval 自行读取前后文。

契约要求：`extra="forbid"`、字段和总事件数有界、canonical digest 稳定、空/畸形输入显式 unavailable、`tool_call_id` 不直接暴露不受信正文。

## 3. Safe Projection

| 工具 | `safe_data` 可保存 | 必须丢弃 |
| --- | --- | --- |
| `read_file` | 工作区相对路径 | 文件正文、绝对根路径 |
| `list_files` | 安全基准路径、glob | 返回文件列表正文 |
| `grep_search` | 安全路径/include、长度受限且过滤后的搜索词 | 匹配源码行 |
| `write_file` / `edit_file` | 相对路径、操作类型、大小/行数变化、digest | 原/新源码正文 |
| `run_shell` | 命令族、子命令、安全目标、allowlist 选项、exit code、测试计数、错误类型 | 原始 command、任意 stdout/stderr |
| 未知工具/命令 | 工具名、安全参数键名、digest、status | 参数值、输出正文、猜测语义 |

投影顺序固定为：读取 typed event → 识别工具专用字段 → 路径归一化与 scope 过滤 → 凭证/敏感串过滤 → 长度限制 → 构造 typed event → 序列化与 digest。任何消费者都不得再次从原始事件或日志解析语义。

## 4. DeepEval Input and Output

- `ArgumentCorrectnessMetric` 接收带 `input_parameters=safe_data` 的真实工具调用。
- `ToolDecisionQuality` GEval 接收公开任务和带 `[seq=N]` 标签的有序 call/result 文本，rubric 只判断工具选择、顺序、绕路和观察到错误后的下一步。
- 两个指标沿用现有 `DeepEvalMetricResult`、模型元数据、timeout/partial/unavailable 处理。reason 被要求引用相关 `[seq=N]`，但作为 advisory 文本展示。
- 不创建机器可读 finding/diagnosis，不映射“主归因”，不调用 ProcessVerifier 合并信号。
- 不运行需要 `expected_tools` 的 `ToolCorrectnessMetric`，也不运行 planning 指标或旧的三个全局主指标。

## 5. Artifact Transport and Report

- worker 在现有 trace 之外写一个 `analysis-trace.json`。
- Harbor 按现有受控文件运输方式下载并复制该文件；缺失、越界或 schema 错误只让 DeepEval unavailable。
- Verified 后处理把经校验的 Analysis Trace 交给现有 DeepEval adapter；不回退到 digest-only trace。
- 报告复用现有 DeepEval metric 列表，按名称展示两项结果的 status、score 和 reason。官方结果仍先展示。
- Opik 继续消费当前 payload，不读取 `analysis-trace.json`。

## 6. Compatibility and Rollback

- `harbor-trace.json`、`ProcessEvidence`、`ProcessVerifier`、`TaskResult` 和 Opik schema 均不变。
- 旧运行没有 Analysis Trace 时，DeepEval 返回 unavailable，不增加兼容转换。
- 回滚只需停止生成/运输新文件并恢复 DeepEval 输入；官方 Harness 与现有确定性证据链仍可独立工作。

## 7. Expected Affected Surface

- 新增：`benchmarks/agent_e2e/analysis_trace.py` 及一个聚焦测试文件。
- 最小修改：worker 写出点、Harbor 文件运输、`deepeval_analysis.py`、`deepeval_metrics.py`、Verified 后处理接线和 `report.py`。
- 明确不修改：`process_verifier.py` 的模型/行为、ProcessVerifier wire model 所在模块、`opik_export.py` 的 trace tree、`lion_code` Runtime/Provider/Tool API。
- 如现有运输结果类型必须登记第二个产物路径，只做该字段所需的局部修改，不借机搬迁模型或统一 artifact abstraction。
