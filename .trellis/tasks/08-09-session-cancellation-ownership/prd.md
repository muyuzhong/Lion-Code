# Session 与 Cancellation 所有权

## Goal

用单一的活动 Session identity 状态和单一的运行取消状态替代 `Agent` 与 `ToolContext` 中的镜像字段，让 SessionLifecycle 成为 Session identity 的唯一生命周期 writer，让 ToolRuntime、Core、Provider、Memory、Autonomy 和前端读取同一取消信号。

## Background

- `Agent.__init__` 当前直接写入 `session_id`、`session_start_time` 和 `_aborted`，再把 Session 与 Cancellation 复制/包装进 `ToolContext`（`lion_code/agent.py:160-161,177,214-227`）。
- `SessionLifecycle.clear_history()` 与 `restore_core_session()` 同时修改 `Agent.session_id` 和 `ToolContext.session_id`，形成手工同步（`lion_code/session_lifecycle.py:55-83,87-130`）。
- `ToolContext` 当前保存 `session_id` 和 `cancellation_fn`，CancellationMiddleware 通过 callback 读取（`lion_code/tooling/context.py:41-63`; `lion_code/tooling/middleware.py:37-43`）。
- `AgentRuntimeCoordinator`、Autonomy、Session Memory、CLI 和应用层直接读取或写入 `_aborted`（`lion_code/agent_runtime.py:217-226,500-501,641-650,757-867`; `lion_code/autonomy_runtime.py:41-49`; `lion_code/session_memory_coordinator.py:48-52`; `lion_code/__main__.py:116`）。
- Core 当前分别声明 Provider cancellation protocol、Tool cancellation protocol，并在 Harness 内创建 `SimpleCancellationToken`（`lion_code/core/provider.py:13-16`; `lion_code/core/tools.py:15-18`; `lion_code/core/harness.py:61-72,94-135`）。
- `lion_code.core.session.SessionState` 已表示 JSONL entry replay 的不可变快照，因此活动 Session identity 类型不能复用同名，避免把持久化投影与生命周期状态混为一谈。

## Requirements

### SC-1：Session identity 唯一状态

- 引入 `SessionIdentityState`，只保存当前活动会话的 `id` 与 `started_at`。
- 引入只读 `SessionView`；ToolContext、Recorder 创建和只读消费者通过该 View 动态读取。
- `SessionLifecycle` 是构造完成后唯一允许执行 new/restore identity mutation 的业务 Owner。
- 删除 `ToolContext.session_id` 以及 clear/restore 中的手工同步。
- `Agent.session_id` 保留为只读门面属性，不保留第二份 mutable value。

### SC-2：Cancellation 唯一状态

- 在 Core 层提供一个可复用的具体 `CancellationToken`，同时满足 Provider 与 Tool 执行信号契约，并提供 `cancelled`、`is_cancelled()`、`cancel()`、`reset()`。
- 引入最小 `ExecutionControl`，拥有该 token 的 begin/cancel 命令；`AgentRuntimeCoordinator` 持有并协调 Memory、Core stream 与 compaction 的取消副作用。
- Agent composition root 把同一个 token 实例交给 Core Harness 与 ToolContext，不创建 callback 镜像。
- 删除 `Agent._aborted`、`ToolContext.cancellation_fn`、重复的 Provider/Tool cancellation protocol 和 Harness 私有 token 实现。
- `Agent.is_aborted` 保留为读取 ExecutionControl 的门面属性；所有原 `_aborted` 读取者改为只读属性/端口，所有写入者改为 begin/cancel 命令。

### SC-3：保持行为不变

- `Agent.abort()` 和 `LionCodingSession.cancel()` 仍同时停止模型流、阻止后续工具执行、取消 Memory 预取与在途 compaction。
- timeout 仍返回 `stop_reason="timeout"`，显式取消仍返回 `stop_reason="aborted"`。
- 新一轮 chat 必须 reset 取消状态；取消后一轮能够继续正常对话。
- `/clear` 生成新 Session ID；restore 使用被恢复的 ID；两者继续使用唯一 JSONL writer 和现有 Session Memory 语义。
- Harness 作为独立 Core 组件仍支持直接 `cancel()`，并把同一 token 传给 Provider 和 Tool。

### SC-4：边界与范围

- 把五条 State Ownership 规则加入 runtime boundary spec，并用架构测试保护关键删除项和 writer 边界。
- 不改 Permission、Plan、Usage、Provider、Memory 或 read freshness 的业务所有权。
- 不增加兼容字段、旧参数 fallback 或新第三方依赖。

## Acceptance Criteria

- [ ] `ToolContext` 只有 `session: SessionView` 和 `cancellation: CancellationView`，不再有 `session_id` / `cancellation_fn`。
- [ ] `Agent` 不再定义或写入 `_aborted`，`is_aborted` 只读取 ExecutionControl。
- [ ] Core Provider 与 Tool 收到同一个 `CancellationToken`；ToolRuntime 不再组合 callback。
- [ ] Session clear/restore 只通过 SessionLifecycle mutation 更新 identity，ToolContext 自动看到新值。
- [ ] clear/restore、显式 abort、timeout、tool cancellation、取消后续聊与 Memory/compaction cancellation 均有 focused tests。
- [ ] 架构测试阻止 `Agent._aborted`、`ToolContext.session_id`、`ToolContext.cancellation_fn` 和 Session identity 镜像回归。
- [ ] 公开的 `Agent.session_id`、`Agent.is_aborted`、`LionCodingSession.session_id` 与 cancel 行为保持不变。
- [ ] focused tests、全量 `pytest`、compileall、import-linter、架构测试、task validate 和 `git diff --check` 全部通过。

## Out of Scope

- PermissionState、PlanRuntime、UsageLedger 和 ProviderManager。
- `read_file_state` / ReadFreshnessTracker 迁移。
- Session JSONL schema、Session Memory、legacy migration 或 Core history 结构变化。
- 新增浏览器、Sandbox 或 SubAgent cancellation 功能；本切片只提供共享 token 边界。
