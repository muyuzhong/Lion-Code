# PR0 Event Stream Kernel Contract

## Goal

将 Event Stream 明确加入 Kernel contract。至少从架构上允许表达 10 个事件：TurnStarted / ModelStarted / ModelDelta / ToolCallRequested / ToolCallCompleted / CompactionStarted / CompactionCompleted / TurnCompleted / TurnFailed / Cancelled。**不要求立刻实现完整事件系统**，但必须避免未来 Supervisor 依赖 Agent 内部私有对象。

## 现状（已核实）

- Kernel 层已有 `core/events.py`：AgentStartEvent / AgentEndEvent / TurnStartEvent / TurnEndEvent / MessageStartEvent / MessageUpdateEvent / MessageEndEvent / ToolExecutionStartEvent / ToolExecutionUpdateEvent / ToolExecutionEndEvent。
- Kernel 层已有 `core/provider_events.py`：AssistantStartEvent / TextStart/Delta/End / ThinkingStart/Delta/End / ToolCallStart/Delta/End / AssistantDoneEvent / AssistantErrorEvent。
- **Compaction 事件只在 `application/events.py`**（CompactionStartEvent / CompactionEndEvent，会话级），Kernel 层无。
- **TurnFailed / Cancelled 无显式事件**（当前用 stop_reason="error"/"aborted" 表达）。
- 事件发射点：`core/loop.py`（TurnStart/TurnEnd）、`providers/stream.py`（流事件）、application 层桥接。

## Requirements

### R1. Kernel 事件契约

在 Kernel 层（`core/events.py` 或同层）声明事件契约，至少覆盖：
- TurnStarted → 已有 `TurnStartEvent`
- ModelStarted → 已有（`AgentStartEvent`/`AssistantStartEvent`，需语义确认）
- ModelDelta → 已有（`TextDeltaEvent`/`ThinkingDeltaEvent`）
- ToolCallRequested → 已有（`ToolCallEndEvent` / `ToolExecutionStartEvent`）
- ToolCallCompleted → 已有（`ToolExecutionEndEvent`）
- CompactionStarted / CompactionCompleted → **Kernel 层缺失**（现仅 application 层）
- TurnCompleted → 已有（`TurnEndEvent`）
- TurnFailed → **缺失**
- Cancelled → **缺失**

### R2. Supervisor 依赖契约

未来 Supervisor（Autonomy/Scheduler/Checkpoint/Retry）订阅事件时，**只能引用 Kernel 公开事件契约**，不得依赖 `Agent._xxx` 私有对象或 `AgentRuntimeCoordinator` 内部状态。

### R3. 不要求全量实现

本 child 不做完整事件系统。允许的选择：
- 声明 Kernel 事件契约类型（含缺失事件的最小契约）并加契约测试；
- 或在现有发射点补最少的缺失事件发射（CompactionStarted/Completed、TurnFailed、Cancelled），并保证现有事件订阅不受破坏。

### R4. 不破坏现有行为

现有 `application/events.py` 的会话级事件、TUI/observer 订阅、`SessionRecorder` 的事件消费必须保持通过。

## Acceptance Criteria

- [ ] Kernel 层存在代码级事件契约，能表达 R3 的 10 个事件（已有事件直接引用；缺失事件有最小契约声明）。
- [ ] 契约有测试覆盖：事件类型集合、判别字段、序列化/别名的稳定契约；若补发射点，测试对应发射时序。
- [ ] 一个"Supervisor 订阅者"示例（测试桩）只通过 Kernel 公开事件契约消费事件，不触碰 Agent 私有对象——以此验证 R2。
- [ ] 现有事件相关测试全通过（tests/core、tests/runtime/test_agent_runtime、tests/integration/test_agent_core_runtime、tests/application/test_coding_session_ports、tests/tui 等）。
- [ ] 不引入 R5 禁止项；不做大规模事件系统重写。

## Notes

- 语义对齐：10 个事件中"ModelStarted/ModelDelta"与现有 provider_events 的关系需在 design 中明确（是别名、包装还是补充）。
- 参考父 design §3 的事件映射表。
