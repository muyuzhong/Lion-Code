# PR③ 运行状态提示与统计行

## Goal

消除"看似卡死"：自动重试与上下文压缩的状态条、耗时统计行、思考耗时显示。
对应设计 PR③（依据归档设计 P0-3 与 P1-8 / D11 / D12；事件契约见归档
research/frontend-current-state.md §3）。

## Requirements

- R1：`ChatProtocolState` 增加 `runtimeNotice`（单值，后到覆盖先到）：
  `auto_retry_start` → `{kind:"retry", attempt, maxAttempts, delayMs, errorMessage}`；
  `compaction_start`/`compaction_started` → `{kind:"compaction", reason}`；
  `auto_retry_end(success)` / `compaction_end(无错误)` 清除；失败走现有
  `failStreaming` 且一并清除状态条（含 `finalizeStreaming` 一切流终态兜底
  清除），避免"状态条说进行中、错误卡片说失败"的双提示。
- R2：ChatInput 正上方窄状态条："API 错误，第 2/5 次重试（3s 后）…" /
  "正在压缩上下文（threshold）…"，zinc 弱提示样式，可自动消失。
- R3：`ChatProtocolState` 增加 `metrics`，reducer 本地打点累计：turn 步数、
  LLM 耗时（message_start→message_end）、工具耗时（tool_execution_start→end）。
- R4：统计行显示在状态条同区域：`N 步 · LLM Xs · 工具 Ys`（无 per-request
  usage，只做耗时类，D11 边界）。
- R5：ReasoningView 折叠头显示 `reasoningDuration` 格式化思考耗时
  （字段已存在于 `ChatMessage`，D12）。

## Acceptance Criteria

- [ ] 运行中阈值/溢出自动压缩出现压缩状态条并在结束后消失；手动 `/compact`
      仅有完成 toast（后端 `bridge.py:_handle_compact` 不经事件桥转发，
      修复需后端改动，归 P2 后端配合项——2026-08-22 实现时核实，原验收
      "手动 /compact 出现压缩状态条"在无后端改动边界内不可达）。构造 API
      失败出现重试状态条（含次数/延迟），成功后消失；失败后状态条清除、
      只留错误卡片。
- [ ] 统计行随执行递增，会话切换/刷新后重置合理（不跨会话累计）。
- [ ] 有思考过程的消息显示思考耗时。
- [ ] `chatProtocol.test.ts` 新增：runtimeNotice 生命周期、metrics 累计
      的 reducer 用例。
- [ ] `npm run build` 通过，dist 产物已更新。

## Out of Scope

- 手动重试按钮、压缩进度百分比、重试历史；TTFT / 解码速率 / token 速率
  （需后端 usage 事件，归 P2 候选池）。

## Notes

- 无前置依赖，可与 PR①② 并行。触碰面：ChatInput / ReasoningView /
  chatProtocol / ChatArea（状态条挂载位）。
- 实现时核实的事件事实（详见 .trellis/spec/frontend/runtime-events-contract.md）：
  应用级 `compaction_start/end`、`auto_retry_start/end` 与核心级
  `compaction_started/completed` 两层事件均已在解码器；溢出恢复链是
  `auto_retry_start` 唯一生产者（provider 级 HTTP 重试在
  `providers/stream.py` 被吞）；阈值压缩只发核心级事件，故
  `compaction_completed` 也需参与清除。
