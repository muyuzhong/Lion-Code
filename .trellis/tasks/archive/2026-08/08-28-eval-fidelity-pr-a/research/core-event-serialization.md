# Core 事件序列化与 Trace 根因(源码确认)

## 1. 事件字段为什么是 camelCase

- `lion_code/core/messages.py:23-32` `WireModel`:
  `ConfigDict(serialize_by_alias=True, alias_generator=_to_camel, ...)`,
  `extra="forbid"`。
- 因此 `TraceRecorder.record`(`benchmarks/agent_e2e/trace.py:84` 起)中
  `_event_payload(event)` 的 `model_dump(mode="json")` 输出 camelCase:
  `ToolExecutionStartEvent.tool_name` → `toolName`,
  `MessageUpdateEvent.assistant_message_event` → `assistantMessageEvent`。
- `trace.py:96` `_find_text(safe_payload, "tool_name", "name")` 找不到
  camelCase 键 → `tool_name` 全 null(backlog 事实 256 事件全 null)。
- 其余字段不受影响:`args`/`type`/`cwd`/`workspace`/`path` 单字键
  camel 化后不变;argument_digest 正常。

## 2. 事件类型列表(`lion_code/core/events.py`)

`agent_start / agent_end / turn_start / turn_end / message_start /
message_update / message_end / tool_execution_start / tool_execution_update /
tool_execution_end / compaction_started / compaction_completed / turn_failed /
cancelled`。另见 `provider_events.py`(assistant 流式,嵌套于
`MessageUpdateEvent.assistant_message_event`)。

## 3. 时间戳来源

- Core 事件模型本身 **没有** started_at/finished_at 字段(backlog 确认)。
- `AgentMessage`(User/Assistant/ToolResult)带
  `timestamp: int`(Unix 毫秒,`messages.py:18-19 current_timestamp_ms`,
  字段在 `messages.py:95/111/133/178/202`)。
- `MessageStart/Update/EndEvent.message`、`TurnEndEvent.message`、
  `ToolExecutionUpdateEvent` 等均携带 message(或其 `partial`);
  `ToolExecutionStart/EndEvent` **不携带** message,只有
  tool_call_id/tool_name/args/result。
- 结论:消息类事件可用 `message.timestamp`(ms→UTC datetime);
  ToolExecution 事件用记录器接收时刻近似(事件刚发生)。

## 4. 目标改动面

- `TraceEvent`(`trace.py:39`)增加 `started_at` / `finished_at`
  (`datetime | None`),与 `DeepEvalTrajectoryEvent`
  (`models.py:493-494`)字段名一致——`deepeval_analysis.py:536-537` 已用
  `getattr(event, "started_at", None)` 投影,贯通零改动。
- 序列化注意:`VersionedModel` `extra="forbid"`(`models.py:25`),
  `write_json` 的 `schema_version="agent-e2e/v1"` 由
  `worker_entrypoint.py` 写、`verified_runner.py:660` 校验字面量。
  新增字段为可选、同 repo 内读写同版本演进,不 bump schema。
- `_find_text` 增加 `"toolName"`;`_event_summary`(`trace.py:322`)的
  选中键同样补 `"toolName"`,使摘要携带工具名(judge reason 引用工具名的
  验收点)。
- 循环候选检测(`_observe_loop`)依赖 tool_name,修复后自动恢复。

## 5. 噪声事实与过滤策略

- `smoke-flask-5014`:256 事件中 195 个 `message_update`(信噪比 ~0.24)。
- `build_deepeval_trajectory`(`deepeval_analysis.py:512`)当前 1:1 投影,
  上限 `MAX_TRAJECTORY_EVENTS = 256`。
- `DeepEvalTrajectoryEvent` 只有 digest/元数据,`message_update` 与
  `message_start/end` 高度冗余(流式快照),直接投影对 judge 无增量价值。
- 策略:投影前按事件类型升采样——丢弃 `message_update`
  (消息边界由 message_start/end 表达),保留其余全部
  (turn/tool/message 边界与 compaction 信号)。事件数期望
  256 → ~61,且不丢失任何工具名/时间戳/循环信号。
- 该过滤只影响 `DeepEvalTrajectory.trace_digest` 与 judge 所见序列,
  不触碰 `TraceEvent` 原始持久化(脱敏红线与 loop 检测不变)。