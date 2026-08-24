# 运行时事件契约（重试/压缩状态条与耗时统计）

## 1. Scope / Trigger

触碰以下任何一项时必读：runtimeNotice（重试/压缩状态条）、metrics（步数/耗时统计行）、
reasoningDuration（思考耗时）、轨迹面板中的重试/压缩事件呈现。

契约来源：PR③ 实现（2026-08-22）对后端两层事件架构的源码核实；行号为当日锚点，漂移后按符号搜。

## 2. 事件架构（两层，非直觉部分）

| 层 | 事件 | 定义 | 是否到达前端 |
| --- | --- | --- | --- |
| 应用级 | `auto_retry_start` / `auto_retry_end`、`compaction_start` / `compaction_end` | `lion_code/application/events.py:51-78` | 是（经 WS 协议） |
| 核心级 | `compaction_started` / `compaction_completed` | `lion_code/core/events.py:74-82` | 溢出/阈值链经 `session._drive` 的 backend.subscribe 队列转发到达 |

关键事实：

- `auto_retry_start` 的**唯一生产者是溢出恢复链**（`session.py:447`）。provider 级
  HTTP 重试（429/5xx）在 `providers/stream.py:115-117` 被 `ProviderRetryEvent` 吞掉，
  不产生该事件——前端渲染纯事件驱动，后端将来接入即自动生效。
- **阈值压缩只发核心级** `compaction_started/completed`（`runtime/agent.py:286/308`），
  不发应用级 start/end，故 reducer 必须让 `compaction_completed` 也清除状态条。
- **手动 `/compact` 完全无事件到达前端**：`bridge.py:_handle_compact` 直接
  `await session.compact()` 不经事件桥，`harness.emit` 只通知运行期活动订阅者
  （`core/harness.py:111-114`）。手动压缩只有完成 toast；补状态条需后端改动（P2）。

## 3. 前端规则

- `runtimeNotice` 单值、后到覆盖先到；清除路径：成功/完成事件 + `failStreaming` +
  `finalizeStreaming`（一切流终态兜底，防事件丢失挂死）。
- `metrics` 为 reducer 本地打点（`Date.now()`，事件无服务端时间戳，D11 边界）：
  turn 步数（`turn_start`）、LLM 耗时（assistant `message_start→message_end` 恰好一对，
  `core/loop.py:370-380`）、工具耗时（`toolCallId` 配对，支持乱序结束）。
  `replace_history` 重置，不跨会话累计。
- `reasoningDuration`：wire/REST 不传输（`/api/messages` DTO 无此字段，
  `server/app.py:249-259`），由前端 `thinking_start/end` 本地配对计时、
  `message_end` 写入；历史消息无数据，ReasoningView 回退显示字符数。

## 4. Tests Required

`desktop/tests/renderer/chatProtocol.test.ts` 维持断言点：runtimeNotice 生命周期
（设置/覆盖/成功清除/失败清除/终态兜底清除）、metrics 累计与重置、
孤儿事件不计时（孤儿 `tool_execution_end`、`message_start` 无 end）、
`formatRunDuration` 进位边界（`119_700→"2m0s"`、`59_999→"1m0s"`）。

## 5. Wrong vs Correct

**Wrong**：期待手动 `/compact` 或 provider HTTP 重试出现状态条（后端不发事件）；
只监听应用级 `compaction_end` 清除状态条（阈值压缩链会挂死）；失败后保留
"进行中"状态条（与错误卡片双提示矛盾）。

**Correct**：状态条纯事件负载驱动；清除挂"成功事件 + failStreaming + finalizeStreaming"
三重路径；耗时统计接受本地时钟近似精度（D11）。
