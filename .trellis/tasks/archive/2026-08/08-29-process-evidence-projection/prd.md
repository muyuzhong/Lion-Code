# PRD: 过程证据投影(TraceEvent → ProcessEvidence)

> 来源:父任务 `08-29-eval-fidelity` 3.1(PR #143 审查反馈问题一)。
> 目标:让 ProcessVerifier 不再猜 Trace,而是读取明确事实。
> 落盘形态已确认:**独立 ProcessEvidence 数组,不改 TraceEvent schema**。

## 1. 背景与目标

真实 Core 事件(`lion_code/core/events.py`)已提供确定性事实:
`ToolExecutionStart/Update/End`(带 `tool_call_id`、`tool_name`、
`args`)、`ToolExecutionEnd.is_error`、`CompactionStarted/Completed`、
`TurnFailed`、`Cancelled`。但当前 `TraceRecorder.record()` 只保留
`tool_name / argument_digest / workspace_fingerprint / summary`,
丢弃 `tool_call_id` 与 `is_error`;路径在脱敏时直接哈希,命令正文
不进 summary(实测 `summary="tool_execution_start: toolName=grep_search"`)。

后果(已用真实 trace 验证):
- `validation_missing` 在 summary 里搜 `pytest` → 真实数据永远找不到;
- `test_tampering` 判断路径属于 src/ 还是 tests/ → 哈希后无法判断;
- `repeated_tool_call` 不按 tool_call_id 聚合 → 一次调用的
  start/update/end 生命周期可能被误算成多次重复调用。

目标:在脱敏**之前**做一次语义化投影,把「明确事实」落盘为独立的
`ProcessEvidence` 数组,与既有 `TraceEvent` 并行,互不干扰。

## 2. 需求

### 2.1 投影输入与输出

- 输入:typed Core event(已确认事件类型:`tool_execution_start` /
  `tool_execution_update` / `tool_execution_end` /
  `compaction_started` / `compaction_completed` / `turn_failed` /
  `cancelled` 等)。
- 输出:`ProcessEvidence` 记录(独立数组,与 events 并列):

```text
tool_call_id            # 工具调用 id(聚合 start/update/end)
tool_phase              # start | update | end
tool_fingerprint        # 稳定工具指纹(工具名 + 参数 digest)
is_error                # end 事件的真实错误标记
target_scope            # source | test | verifier(路径哈希前分类)
validation_command      # true/false(与任务验证命令比对)
validation_command_id   # 命中时:命令编号(如 "validation-0")
command_digest          # 命令正文摘要在脱敏前计算
compaction              # started | completed | None
termination             # turn_failed | cancelled | None
```

### 2.2 隐私与脱敏边界(不变式)

- **不保存**:完整命令、文件路径、工具输出。
- 路径:`lion_code/meta_agent.py → target_scope=source`(路径在哈希前
  分类,落盘只保留 `target_scope` + 路径 digest)。
- 命令:`pytest -q` 在脱敏前与任务声明验证命令对比 → 落盘
  `validation_command_id="validation-0"` + `command_digest`,不存正文。
- 其余敏感字段沿用现有 `sanitize_payload` 脱敏规则。

### 2.3 与 TraceEvent 的关系

- **独立数组**:`TraceRecorder.write_json` 同时写 `events` 与
  `evidence`;`TraceEvent` 本身、`TraceSummary`、`payload_digest`、
  既有 trace 测试零改动。
- 旧 trace(无 evidence 数组)可被新 reader 读取,evidence 为空。
- `TraceRecorder.record()` 在记录事件的同时对 typed event 做投影
  (仅对可识别的事件;未知事件跳过投影,不抛错)。

### 2.4 可审计性

- evidence 与 events 通过 `sequence` 关联(取被投影事件的 sequence)。
- 投影函数纯函数式:同一事件必得同一 evidence(确定性)。

## 3. 验收准则

- [ ] `TraceRecorder.record()` 对 `tool_execution_start/end` 产出
      `ProcessEvidence`(tool_call_id / tool_phase / is_error /
      tool_fingerprint 齐全)。
- [ ] 路径分类:构造 source/test/verifier 三类路径,投影出正确
      `target_scope`;落盘 JSON 中不存在原始路径。
- [ ] 验证命令:构造 `pytest -q` 执行,投影出
      `validation_command=true` + 正确 id + digest;命令正文不出现在
      JSON 中。
- [ ] compaction / termination 事件正确投影。
- [ ] 未知事件不投影、不抛错;`write_json` 输出含 `evidence` 数组,
      旧文件读取不崩溃。
- [ ] 新增 `tests/benchmarks/test_process_evidence.py`(或并入
      test_trace.py 的扩展);tests/benchmarks 全绿。
- [ ] 隐私断言:测试遍历序列化 JSON,断言不含命令 / 路径 / 输出
      明文。

## 4. 非目标

- 不修改 `TraceEvent` schema 与既有 `TraceSummary` 语义。
- 不做 ProcessVerifier 规则重写(子任务二)。
- 不保存任何「可还原」的命令/路径/输出。