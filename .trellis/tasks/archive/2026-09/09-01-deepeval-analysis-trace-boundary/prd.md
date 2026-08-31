# 修复 DeepEval Analysis Trace 边界问题

## Goal

让 Analysis Trace 成为真正的 DeepEval 旁路诊断输入：它的采集、构造或写盘失败时只丢失 `analysis-trace.json`，不改变 Agent worker 的正式结果；同时让 sequence 证据保持诚实，并移除没有校准依据的聚合 DeepEval pass/fail gate。

## Background and Confirmed Facts

- `TraceRecorder.record()` 订阅 Agent 的 typed Core event 流，并在保存现有 `TraceEvent`/`ProcessEvidence` 后同步调用 `AnalysisTraceProjector.project()`（`benchmarks/agent_e2e/trace.py:116-168`）。`record_tool_call()` 也直接调用该投影器（`benchmarks/agent_e2e/trace.py:169-225`）。
- `run_agent_worker()` 通过 `agent.subscribe(recorder.record)` 接入事件流；未隔离的监听器异常会落入 worker 的通用异常分支并生成 `WorkerStatus.ERROR`（`benchmarks/agent_e2e/agent_worker.py:101-125`）。
- `TraceRecorder.build_analysis_trace()`/`write_analysis_trace()` 当前直接构造并校验 Analysis Trace（`benchmarks/agent_e2e/trace.py:244-255`）。`worker_entrypoint.main()` 在已经写完 `worker-result.json`、`trace.json` 后直接写 `analysis-trace.json`，没有旁路异常隔离（`benchmarks/agent_e2e/worker_entrypoint.py:86-90`）。
- `AnalysisTraceProjector.project()` 目前没有失败状态；`AnalysisTrace.write_json()` 会先校验 digest，再执行目录创建和写文件（`benchmarks/agent_e2e/analysis_trace.py:222-229,260-310`）。
- `_with_sequence_reference()` 当前在 Judge reason 未包含 `[seq=...]` 时自动使用第一条事件的 sequence（`benchmarks/agent_e2e/deepeval_analysis.py:746-762`），这可能制造与判断无关的伪证据。
- `_analysis_from_metrics()` 和 `parse_deepeval_analysis()` 当前填充 `score_gate`，`DeepEvalScoreGate` 以 `0.5` 阈值合并指标（`benchmarks/agent_e2e/deepeval_analysis.py:600-680`、`benchmarks/agent_e2e/models.py:760-818`）。Markdown 还显示“judge 评分门禁”（`benchmarks/agent_e2e/report.py:260-319`）。当前阶段没有经过 calibration 的阈值解释，不应产生第二套正式或准正式判定。

## Requirements

### R1. Analysis Trace 故障完全旁路隔离

- Analysis Trace projector 维护明确的失败状态。一次投影异常后停止后续 Analysis Trace 采集，并继续允许 `TraceRecorder` 记录现有正式事件和过程证据。
- Analysis Trace 的投影、构造、digest 校验或写盘异常不得从 Agent event listener、worker 或 worker entrypoint 冒泡为正式执行失败。
- Analysis Trace 失败只允许表现为 `analysis-trace.json` 缺失；既有 `worker-result.json`、`trace.json`、patch 导出、Harbor/Harness 结果和 `WorkerResult` 必须保持原有语义。
- 现有“缺少 Analysis Trace → DeepEval unavailable”的后处理降级路径继续生效，不通过 legacy digest-only trajectory 重建语义输入。
- 不新增错误层、诊断模型或通用 artifact abstraction；只在现有投影器和 worker 写出边界增加最小隔离。

### R2. Sequence 证据必须由 Judge 提供

- Judge reason 已包含 `[seq=N]` 时原样保留受控 reason，不重写 sequence。
- Judge reason 未包含 sequence 定位时，不得自动选择第一条 Analysis Trace 事件；reason 应明确标注“Judge 未提供 sequence 定位”，并保持现有 reason 脱敏和长度上限。
- 空 reason 仍使用现有受控完成/失败语义，再附带显式的 sequence 缺失说明；不得伪造事件关联。

### R3. 删除聚合 DeepEval score gate

- 删除 `DeepEvalScoreGate`、`DeepEvalAnalysis.score_gate`、`_score_gate()` 及其生产计算和报告渲染；DeepEval 不再合并多个指标为“通过/未达”。
- Markdown/JSON 的 DeepEval 结果只保留现有两项 metric 的独立状态、分数、reason 及已有运行元数据；不再输出“judge 评分门禁”或聚合计数。
- 本次不改变官方 Harness/Harbor/`TaskResult`/`verified_exit_code` 的判定语义，也不把任一 DeepEval 分数变成新的 gate。
- 仅删除本任务直接涉及的 aggregate gate 语义；不迁移 `ProcessVerifier`，不引入新的 metric、diagnosis 或校准系统。

## Acceptance Criteria

- [ ] 注入一次会抛异常的 Analysis Trace 投影，`TraceRecorder.record()` 和真实/伪造 worker 运行仍返回原本的 `WorkerStatus`，且正式 `TraceEvent`/`ProcessEvidence` 不受影响；后续投影调用不再执行。
- [ ] 让 Analysis Trace 构造或写盘失败，worker entrypoint 仍完成已有结果和 patch/legacy trace 写出，返回成功的 entrypoint 结果；`analysis-trace.json` 不存在（包括清理可能的部分写入）。
- [ ] 缺失 `analysis-trace.json` 的 Verified 后处理仍将 DeepEval 标为 `unavailable`，不调用 Judge，不改变官方 `task_result`、patch、Harbor 或 Harness 字段。
- [ ] Judge reason 已有 `[seq=5]` 时仍保留该引用；没有 sequence 时包含“Judge 未提供 sequence 定位”，且不包含自动注入的第一条事件 sequence。
- [ ] DeepEval analysis、fixture 解析、Verified composition 和 Markdown 报告均不再产生或显示 `score_gate`/“judge 评分门禁”；两项 metric 的独立 score/reason 仍可正常序列化和展示。
- [ ] 现有 `harbor-trace.json`、`ProcessEvidence`、`ProcessVerifier`、Opik payload、官方 Harness 结果和 CLI 退出码测试不因本任务改变。
- [ ] 受影响的 benchmark tests、定向 compile 检查和 `git diff --check` 通过；不运行无关的全量质量扫描。

## Out of Scope

- 重做 Analysis Trace 的安全白名单、shell family、pytest target 或事件 schema。
- `ProcessVerifier`、First-Error Attribution、Harbor verifier、官方 Harness、Opik trace tree 或 Lion Runtime 的迁移/重构。
- 新增 `AnalysisDecision`、`DeepEvalDiagnosis`、finding/aggregate 模型、通用错误系统、metric registry 或 calibration pipeline。
- 三题真实 Linux/Cloud 重跑和 DeepEval 分数 calibration；本任务只保证失败降级和分数旁路语义。
- 修改已有非 aggregate 的 DeepEval metric 采样、脱敏、输入 digest 或模型指纹行为，除非删除 gate 的直接引用要求同步调整其测试/文档。

## Open Questions

无。用户已明确要求保留现有总体架构，只修复上述三个边界问题；未校准的分数不参与任何聚合判定。
