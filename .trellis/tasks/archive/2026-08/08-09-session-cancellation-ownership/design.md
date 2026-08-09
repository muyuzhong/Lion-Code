# Session 与 Cancellation 所有权设计

## 1. Session Identity

新增 `lion_code/session_identity.py`：

- `SessionView(Protocol)` 暴露只读 `id`、`started_at`。
- `SessionIdentityState` 保存活动 identity，并提供由 SessionLifecycle 调用的 `reset(id, started_at)`。

不用 `SessionState` 作为类型名，因为 `lion_code.core.session.SessionState` 已经是 JSONL replay 的不可变结果。两个概念同名会模糊持久化投影与活动生命周期状态。

Agent 在 composition root 中创建一个 `SessionIdentityState` 引用：

- ToolContext 收到同一对象的 `SessionView`。
- Agent 的 `session_id` / `session_start_time` 变成只读 facade property。
- AgentRuntimeCoordinator 的 Session host 暴露 `session_state`，不再暴露可写的 `session_id` / `session_start_time`。
- SessionLifecycle 的 new/restore 路径只调用 `session_state.reset(...)`。
- SessionRecorder、repository load 和 run result 均动态读取 `session_state.id`。

## 2. Cancellation

新增 `lion_code/core/cancellation.py`：

- `CancellationView`：只读 `cancelled` / `is_cancelled()`。
- `CancellationToken`：具体可变实现，增加 `cancel()` / `reset()`。

删除 `core.provider.CancellationToken` protocol、`core.tools.ToolCancellationToken` protocol 和 Harness 的 `SimpleCancellationToken`。Provider、Tool、Harness 与 ToolRuntime 统一依赖 Core 的 Cancellation 类型。

新增 `lion_code/execution_control.py`：

- `ExecutionControl` 持有唯一 token。
- `begin()` reset 当前运行状态。
- `cancel()` 设置取消状态。
- `cancelled` / `cancellation` 提供只读状态视图。

Agent 只在构造时创建 ExecutionControl 并交给 AgentRuntimeCoordinator；不把 token 状态镜像回自身。AgentRuntimeCoordinator：

1. chat 开始时调用 `execution.begin()`；
2. abort/timeout 调用 `execution.cancel()`；
3. abort 继续取消 Memory prefetch 与 compaction task；
4. Core Harness 使用同一个 token 终止 Provider stream 和 Tool 调用；
5. outcome 同步只读取 token，不写宿主字段。

## 3. ToolContext and Adapter Data Flow

```text
ExecutionControl
      |
      +-- owns --> CancellationToken
                       |
             +---------+----------+
             |                    |
       AgentHarness          ToolContext
       Provider/Tool         CancellationView
```

ToolContext 改为依赖上下文：

```python
@dataclass(slots=True)
class ToolContext:
    session: SessionView
    cancellation: CancellationView
    cwd: Path
    controller: AgentToolController
    registry: ToolRegistry
    ...
```

Tool adapter 仍把 Core signal 交给 ToolRuntime，以支持独立组装不同 token 的测试/嵌入场景；ToolRuntime 通过只读组合 View 处理两个不同实例，不再创建 lambda callback，也不保存第二份 mutable state。Lion 正常 composition 中两者是同一实例，直接复用原 context。

## 4. Public and Host Contracts

- `RuntimeIdentityHost` 删除 `_aborted`，增加只读 `is_aborted`。
- `AutonomyHost` / `SessionMemoryHost` 同样改读 `is_aborted`。
- `SessionStateHost` 删除可写 identity 字段，增加 `session_state`。
- `Agent.is_aborted`、`Agent.session_id` 和 `Agent.session_start_time` 是 facade，不是 Owner。
- CLI/TUI 不直接访问 mutable token。

## 5. Invariants

- 同一 Agent composition 中只有一个活动 `SessionIdentityState`。
- 构造完成后只有 SessionLifecycle 调用 identity reset。
- 同一运行中 Core、Provider、ToolRuntime 和 middleware 观察同一 cancellation state。
- 取消状态在新一轮开始前 reset，不能泄漏到下一轮。
- timeout 与 explicit abort 共用取消命令，但最终 stop reason 仍由 timeout 标志区分。
- 取消不创建第二条 history、Provider、Recorder 或 JSONL writer。

## 6. Compatibility and Migration

本项目不保留向后兼容。内部构造点和测试 fixture 直接改用新字段；旧 `ToolContext(session_id=..., cancellation_fn=...)` 立即删除。公开 facade properties 保留是产品 API，而不是旧状态兼容层。

## 7. Rollback

该切片没有数据迁移。回滚点是单个中文提交；回滚同时恢复旧 runtime 字段、ToolContext 参数、测试和 spec，不影响 JSONL 或 Memory 数据。
