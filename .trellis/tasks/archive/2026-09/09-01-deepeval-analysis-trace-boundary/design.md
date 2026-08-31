# Design: DeepEval Analysis Trace 边界修复

## 1. Boundary and data flow

```text
typed Core events
        |
        +--> TraceRecorder --> TraceEvent/ProcessEvidence --> trace.json
        |                         （正式评测链，保持原行为）
        |
        +--> AnalysisTraceProjector --best effort--> analysis-trace.json
                                      |
                                      +--> DeepEval
                                           missing => unavailable

worker-result.json / patch / Harbor / Harness
        ^
        +-- 不读取、不依赖 Analysis Trace 的成功状态
```

Analysis Trace 仍然只是 `benchmarks/agent_e2e` 内供 DeepEval 使用的旁路
artifact。不会把失败状态写进 `TraceEvent`、`ProcessEvidence`、`WorkerResult`
或 `TaskResult`，也不会让 Opik 读取新文件。

## 2. Failure containment contract

### Collection

`AnalysisTraceProjector` 增加私有失败状态，并让 `project()` 成为自己的
containment boundary：

- 未失败时执行现有安全投影逻辑；投影过程中出现 `Exception` 时只将状态置为
  failed，返回空结果，不暴露异常文本。
- failed 状态下后续 `project()` 直接 no-op，因此不会反复触发同一异常，也不会
  让同步 Agent listener 抛错。
- `TraceRecorder` 继续先保存既有 `TraceEvent` 与 `ProcessEvidence`，Analysis
  Trace 的旁路失败不能回滚或覆盖它们。

### Construction and writing

- 失败 projector 的 `build()` 抛出现有 `AnalysisTraceUnavailable`，而不是构造
  一个不完整的语义轨迹；这会沿用下游“artifact 缺失 → DeepEval unavailable”
  语义。
- `worker_entrypoint.main()` 只对 `recorder.write_analysis_trace(...)` 建立一个
  最小的 best-effort `try/except Exception` 边界。失败时清理精确的
  `ANALYSIS_TRACE_PATH`（包含可能的部分写入），然后继续已有 result、legacy
  trace 和 patch 流程。
- 不引入日志、错误 registry 或新的异常层。Analysis Trace 的失败原因不写入
  正式结果，避免把投影器异常中的原始参数带出容器。
- 不捕获 `BaseException`/取消语义；进程级退出和显式取消仍按既有 worker
  语义处理。普通投影/构造/写盘 `Exception` 必须被旁路吸收。

## 3. Honest sequence references

保留 `_with_sequence_reference()` 作为 reason 的单一受控出口，但改变其缺失
分支：

- 已有 `[seq=N]` 的 reason 只做现有脱敏/长度约束，不修改 Judge 已提供的
  定位。
- 没有 sequence 的 reason 不再读取 `analysis_trace.events[0]`；在受控长度内
  附加固定说明 `（Judge 未提供 sequence 定位）`。
- 空 reason 仍先使用现有的 `DeepEval metric completed` 基础文本，再附加相同
  说明。这样报告明确区分“Judge 没有给证据”和“有证据但关联到某序列”。

## 4. Remove aggregate gate only

删除聚合 gate 的完整引用链：

```text
DeepEvalScoreGate model
        -> DeepEvalAnalysis.score_gate
        -> _score_gate(metrics)
        -> report._gate_conclusion()
```

DeepEval 仍输出固定的两个独立 metric 结果、已有 status/score/reason、采样与
身份信息。为保持本次修改最小，已有 `DeepEvalMetricResult` 的逐项字段和 SDK
metric 构造不在本任务中迁移；但这些字段不再被合并成 aggregate pass/fail，
报告也不再出现“judge 评分门禁”或聚合计数。官方 Harness verdict、Harbor
结果、patch、`TaskResult` 和退出码保持原有来源与顺序。

## 5. Affected files and ownership

| Area | Expected change |
| --- | --- |
| `benchmarks/agent_e2e/analysis_trace.py` | projector failed state, no-op after failure, unavailable construction |
| `benchmarks/agent_e2e/trace.py` | only if needed to expose the existing projector boundary; preserve formal trace path |
| `benchmarks/agent_e2e/worker_entrypoint.py` | best-effort Analysis Trace write and exact-path cleanup |
| `benchmarks/agent_e2e/deepeval_analysis.py` | honest missing-sequence reason; remove aggregate gate construction |
| `benchmarks/agent_e2e/models.py` | remove `DeepEvalScoreGate` and `DeepEvalAnalysis.score_gate` |
| `benchmarks/agent_e2e/report.py` | remove aggregate gate line/helper; keep independent metric rows |
| tests under `tests/benchmarks/` | regressions for isolation, honest evidence and gate absence |
| `docs/agent-e2e-verified-run.md` / agent-e2e spec | state missing-artifact fallback and no aggregate gate |

No change is planned for `lion_code`, `ProcessEvidence`, `ProcessVerifier`, Opik
payloads, official Harness execution, or the Harbor patch contract.

## 6. Compatibility and rollback

- The existing evaluation schema version remains unchanged. Missing
  `analysis-trace.json` is already a supported DeepEval unavailable condition.
- Removing the explicitly unwanted aggregate field is intentional; old reports that
  contain it are not regenerated or used as a new input contract by this task.
- Rollback is local to the Analysis Trace sidecar, reason formatter and aggregate
  gate references. The existing `trace.json`, patch and official result paths remain
  independently usable.

## 7. Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| A malformed typed event raises in the projector | Catch at projector boundary, mark failed, and assert later events are no-op |
| A writer leaves a partial file | Remove only the controlled `analysis-trace.json` path in the worker catch block |
| A Judge reason loses a valid location | Preserve any existing `[seq=...]` and test a non-first sequence |
| Hidden aggregate gate reference survives | Search production, tests, docs and exports after the edit; targeted report/contract tests must assert absence |
| Formal result is accidentally changed | Assert worker/entrypoint/Verified tests preserve `WorkerResult`, patch and `task_result` while Analysis Trace is unavailable |
