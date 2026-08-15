# PR0 Event Stream Kernel Contract — Design

## 1. 目标

把 Kernel Event Stream 固化为契约：Supervisor 订阅事件时只引用 Kernel 公开事件类型，不触碰 `Agent._xxx` 私有对象。本 child 只补**最小契约**，不做完整事件系统。

## 2. 现状事件流（已核实）

- 发射链路：`core/loop.py::run_agent_loop()` 生成 `AgentEvent` → `core/harness.py::AgentHarness` 订阅转发（含修复事件）→ `agent_runtime.py::LionAgentRuntime` 包装 → coordinator/application 消费。
- Kernel 事件集合（`core/events.py` 的 `AgentEvent` union）：AgentStart/End、TurnStart/End、MessageStart/Update/End、ToolExecutionStart/Update/End。
- Kernel 流事件（`core/provider_events.py`）：AssistantStart、Text*/Thinking*/ToolCall*、AssistantDone、AssistantError。
- 会话级事件（`application/events.py`）：SessionAgentEnd、AgentSettled、QueueUpdate、CompactionStart/End、AutoRetryStart/End、Session/Provider/Thinking changed。
- **缺口**（PR 要求的 10 事件中，Kernel 无法表达）：CompactionStarted、CompactionCompleted、TurnFailed、Cancelled。
  - Compaction 事件现仅在 application 层；coordinator 的 `compact_core_context_if_needed()`（agent_runtime.py）是发射驱动点。
  - TurnFailed/Cancelled 现用 `stop_reason`（"error"/"aborted"）隐含表达，无独立事件。

## 3. 设计决策

### 3.1 在 `core/events.py` 声明缺失的 Kernel 契约事件

新增（保持 Pi-compatible WireModel + discriminated union）：

```python
class CompactionStartedEvent(WireModel):
    type: Literal["compaction_started"] = "compaction_started"
    reason: Literal["threshold", "overflow", "manual"] = "threshold"

class CompactionCompletedEvent(WireModel):
    type: Literal["compaction_completed"] = "compaction_completed"
    reason: Literal["threshold", "overflow", "manual"] = "threshold"
    aborted: bool = False

class TurnFailedEvent(WireModel):
    type: Literal["turn_failed"] = "turn_failed"
    message: AgentMessage          # 携带 error_message / stop_reason="error"

class CancelledEvent(WireModel):
    type: Literal["cancelled"] = "cancelled"
    message: AgentMessage | None = None   # 若已生成部分消息则携带
```

并加入 `AgentEvent` union。这样 `core/events.py` 即成为 Kernel 事件契约的单一权威源。

### 3.2 语义映射（10 事件 → Kernel 表达）

| 契约事件 | Kernel 表达 | 动作 |
|---|---|---|
| TurnStarted | `TurnStartEvent` | 已存在，契约测试引用 |
| ModelStarted | `AssistantStartEvent`（provider_events） | 已存在；契约测试确认 |
| ModelDelta | `TextDeltaEvent`/`ThinkingDeltaEvent` | 已存在；契约测试确认 |
| ToolCallRequested | `ToolCallEndEvent` / `ToolExecutionStartEvent` | 已存在；契约测试确认 |
| ToolCallCompleted | `ToolExecutionEndEvent` | 已存在；契约测试引用 |
| CompactionStarted | `CompactionStartedEvent`（新增） | 补声明 + 发射点 |
| CompactionCompleted | `CompactionCompletedEvent`（新增） | 补声明 + 发射点 |
| TurnCompleted | `TurnEndEvent` | 已存在；契约测试引用 |
| TurnFailed | `TurnFailedEvent`（新增） | 补声明 + 发射点 |
| Cancelled | `CancelledEvent`（新增） | 补声明 + 发射点 |

### 3.3 最小发射点（不破坏现有行为）

- **TurnFailedEvent / CancelledEvent**：在 `core/loop.py::run_agent_loop()` 的收尾处，依据最终 assistant message 的 `stop_reason` 与 `signal.is_cancelled()` 发射。它们是纯新增事件，不改变现有 `TurnEndEvent` 发射。
- **CompactionStartedEvent / CompactionCompletedEvent**：在 coordinator 的压缩驱动点（`agent_runtime.py::compact_core_context_if_needed` / 溢出压缩路径）发射，作为 `AgentEvent` 流入现有订阅链。application 层现有 `CompactionStartEvent` 保持不动（会话级语义），Kernel 契约事件是底层事实事件；二者可共存。若实现中发现改动风险高，可降级为"仅声明契约类型 + 契约测试"，并在 implement 中记录原因（PR 允许不立即实现完整事件系统）。

### 3.4 Supervisor 订阅契约测试

新增一个测试桩"Supervisor 订阅者"：只 import `lion_code.core.events`（与 `core/provider_events.py`）的公开类型，订阅并消费事件流，断言它**不 import** `agent`/`agent_runtime`/`AgentRuntimeCoordinator` 私有字段。用 AST 或直接 import 断言验证。这就是"Supervisor 不依赖 Agent 私有对象"的可执行证据。

### 3.5 契约测试（tests/core/test_event_contract.py 或 tests/architecture/）

- 断言 `core/events.py` 的 `AgentEvent` union 成员能表达全部 10 个契约事件（类型存在 + 判别字段 + 可序列化/反序列化）。
- 断言新增事件的判别值（`compaction_started` 等）不与现有冲突。
- 断言 Supervisor 订阅者只经公开契约（3.4）。

## 4. 边界与约束

- 不重写事件系统；不改变现有事件的字段/判别值（向后兼容）。
- `application/events.py` 现有会话级事件、`SessionRecorder` 消费、TUI/observer 订阅不受影响。
- 不新增 ServiceLocator / CapabilityContext / Null 事件。
- `core/` 不得因新增事件引入对 `agent_runtime`/`providers`/`tooling` 的依赖（发射点若是 Harness，只在 Harness 侧 import Kernel 事件类型，方向正确）。

## 5. 验收验证命令

- `python -m pytest tests/core/test_event_contract.py -q`（新增契约测试）
- `python -m pytest tests/core tests/integration/test_agent_core_runtime.py tests/runtime/test_agent_runtime.py tests/application/test_coding_session_ports.py tests/tui -q`
- `lint-imports --no-cache`（确认 core 依赖方向）
- `python -m pytest tests/architecture -q`
