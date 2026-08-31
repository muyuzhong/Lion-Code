# Implementation Plan: DeepEval Analysis Trace 边界修复

## Preconditions

- 任务已获用户授权创建；只有用户批准最终 planning summary 后，才运行
  `task.py start` 并进入实现。
- 实现前加载 `trellis-before-dev`，再次确认当前分支和 dirty worktree；现有
  未跟踪 `agents/` 属于用户内容，不纳入提交、不移动、不删除。
- 只修改 Analysis Trace、DeepEval aggregate gate 的直接引用、相关测试和
  评测文档；不触碰 `lion_code`、ProcessVerifier、Opik 或官方执行链。

## Ordered Checklist

1. **先建立失败回归**
   - 在 benchmark tests 中注入一个会抛异常的 Analysis Trace 投影器，证明
     `TraceRecorder`/worker 的正式结果仍为原状态，并证明失败后不会继续投影。
   - 覆盖 projector build 失败、worker Analysis Trace 写盘异常和部分文件清理；
     result、patch、legacy trace 的断言保持独立。
   - 增加缺少 `[seq=...]` 的 Judge reason 用例，以及已有非首条 sequence 的
     reason 保留用例。
   - 将现有 score gate 测试改为断言没有 aggregate gate，保留两项独立 metric
     score/reason 和既有 sampling/status 语义。

2. **实现 Analysis Trace 采集隔离**
   - 在 `AnalysisTraceProjector` 增加 failed 状态；投影异常时标记并返回，后续
     project 调用 no-op。
   - failed projector 构造 Analysis Trace 时使用现有
     `AnalysisTraceUnavailable`，不生成不完整 artifact。
   - 保持 `TraceRecorder` 的 `TraceEvent`、`ProcessEvidence`、loop candidate
     和 summary 路径不变。

3. **实现 worker 写盘隔离**
   - 在 `worker_entrypoint` 只包裹 `write_analysis_trace` 调用，捕获普通
     `Exception`，清理精确的 `ANALYSIS_TRACE_PATH`，然后返回既有成功路径。
   - 不扩大到 `worker-result.json`、patch 或 legacy `trace.json` 的异常处理；这些
     仍代表正式 worker 产物。

4. **修正 sequence 语义**
   - 删除从 `analysis_trace.events[0]` 自动补 sequence 的行为。
   - 对缺少定位的 reason 附加固定、脱敏、长度受限的
     `（Judge 未提供 sequence 定位）`；已有 `[seq=N]` 只保留原定位。

5. **删除 aggregate score gate**
   - 删除 `DeepEvalScoreGate`、`DeepEvalAnalysis.score_gate`、`_score_gate()`
     及所有生产调用、导出和测试构造。
   - 从 Markdown report 删除“judge 评分门禁”及聚合计数；保留两项 metric 的
     独立结果和已有报告上下文。
   - 同步修正 `docs/agent-e2e-verified-run.md` 与
     `.trellis/spec/backend/agent-e2e-evaluation.md`，明确旁路失败和 no-gate
     契约，不修改历史归档任务文件。

6. **Targeted validation**
   - 运行受影响 benchmark tests、定向 compile 和 `git diff --check`。
   - 搜索 `score_gate`、`DeepEvalScoreGate`、`judge 评分门禁` 的生产/测试/文档
     残留，确认只有历史归档记录（若保留）或零残留，不把历史文档误改成当前
     契约。
   - 检查 diff 只包含任务直接路径，特别确认 `agents/` 不在 diff 中。

## Validation Commands

```powershell
python -m pytest tests/benchmarks/test_analysis_trace.py tests/benchmarks/test_trace.py tests/benchmarks/test_agent_worker.py tests/benchmarks/test_eval_analysis_observability.py tests/benchmarks/test_verified_contracts.py tests/benchmarks/test_verified_cli_composition.py tests/benchmarks/test_verified_execution_chain.py -q
python -m compileall -q benchmarks/agent_e2e tests/benchmarks
git diff --check
```

如新增独立 `test_worker_entrypoint.py`，将其加入同一 targeted pytest 命令；不运行
默认全量测试、coverage、全局 lint 或完整 mypy。

## Risk and Rollback Points

- **投影异常仍污染 worker：** 在继续其它修改前先通过 worker regression；若失败，
  回滚到只含 projector containment 的最小变更。
- **部分 Analysis Trace 文件残留：** 使用受控临时路径测试失败写盘，并断言目标
  文件不存在；不改变其它 artifact 的清理策略。
- **sequence 证据被重写：** 同时测试 `[seq=5]` 保留和无 sequence 的显式缺失，
  避免只用第一条事件的正例。
- **aggregate gate 残留或 API 断链：** 先完成全引用搜索，再运行 model/report/
  composition tests；不引入替代 gate。
- **范围漂移：** 最终 diff 审查禁止新增诊断模型、ProcessVerifier/Opik 接线或
  `lion_code` 修改。

## Completion Gates

- 所有 PRD acceptance criteria 可由 targeted tests 或静态搜索证明。
- 最后一次 `git diff --check` 通过，测试失败如有 baseline 噪声需与本次改动分开
  归因。
- 完成 Trellis check、spec 更新和用户要求的提交流程后再归档任务；本任务不自动
  merge 或 push。
