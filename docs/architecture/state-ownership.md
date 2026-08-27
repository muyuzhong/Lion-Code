# 状态所有权契约 (State Ownership)

本文档定义 Lion-Code 关键状态的单一所有者（Single Owner）、创建者、修改者、读取者以及持有禁令。

## 关键状态所有权总表

| 状态类别 | 唯一所有者 (Single Owner) | 初始创建者 | 状态修改者 | 状态读取者 | 生命周期 | 严禁持有者 |
|---|---|---|---|---|---|---|
| **活跃对话消息 (Active Messages)** | `ConversationRuntime` (`runtime/conversation.py`) | `Composition Root` (`build_agent_composition`) | `ConversationRuntime` (通过 `AgentHarness.replace_messages` / `prompt`) | `AgentRuntime`, `ContextRuntime`, `MetaAgent` | 单次会话/连续对话期 | `SessionRuntime`, `ProviderController`, `Supervisor` (严禁维护第二份副本) |
| **持久化会话历史 (Durable Session)** | `SessionRuntime` (`runtime/session.py`) | `Composition Root` | `SessionRuntime` (通过 `SessionRecorder` 追加 Entry / 压缩记录) | `SessionRepository`, `MetaAgent`, `CodingSessionBackend` | 跨进程/持久保存在磁盘 JSONL | `ConversationRuntime`, `ContextRuntime`, `core/loop.py` |
| **会话身份 (Session Identity)** | `SessionIdentityState` (`runtime/session_identity.py`) | `Composition Root` | `SessionRuntime` (`new_session`, `restore` 时调用 `.reset()`) | `SessionRuntime`, `PlanRuntime`, `ToolContext` | 随会话切换而重置 | 其他任何模块严禁直接写 `_id` 或 `_started_at` |
| **上下文压缩与限制缓存** | `ContextRuntime` (`runtime/context.py`) | `Composition Root` | `ContextRuntime` (`resolve_model_limits`, `summarize`, `on_compacted`, `invalidate_model_limit_cache`) | `AgentRuntime` (`should_compact_now`, `prepare_context`) | 随活跃会话生命周期 | `ConversationRuntime`, `SessionRuntime`, `CapabilityRegistry` |
| **Provider 配置与 Thinking** | `ProviderController` (`runtime/provider.py`) | `Composition Root` | `ProviderController` (`configure`, `set_thinking_level`, `restore_configuration`) | `ProviderConfigurationProjection` (只读), `MetaAgent`, `SettingsPort` | 动态变更 / 跨会话 | `AgentRuntime` (严禁持有 Controller), `ConversationRuntime` (只接收命令) |
| **工具注册与激活状态** | `ToolRegistry` (`tooling/registry.py`) | `Composition Root` 或调用方 | `ToolRegistry` (`register`, `activate`, `deactivate`) | `ToolRuntime`, `PromptComposer`, `adapt_active_tools` | 单个 Agent 实例生命周期 | `core/harness.py`, `core/loop.py` |
| **权限模式与确认缓存** | `PermissionController` (`permission_state.py`) | `Composition Root` | `PermissionController` / `PermissionMiddleware` (`confirm`) | `PermissionMiddleware`, `ToolContext`, `MetaAgent` | 单个 Agent 实例生命周期 | 严禁绕过 Controller 直接向 `state.confirmed_values` 或 `state.mode` 写入 |
| **累计用量与预算** | `UsageLedger` (`usage.py`) | `Composition Root` | `UsageObserver` (订阅事件流累加), `UsageLedger.record_turn` | `AgentRuntime.before_core_tool_calls`, `BudgetPolicy`, `MetaAgent` | 单个 Agent 实例/会话生命周期 | `AgentHarness` (预算在 Core 工具边界生效，禁止传参给 Harness) |
| **单次运行取消令牌** | `ExecutionControl` (`runtime/execution.py`) | `Composition Root` | `ExecutionControl` (`begin` 重置, `cancel` 中止) | `AgentRuntime.abort`, `ToolContext`, `CancellationView` | 单次 `chat` / `run` 运行期 | 外部组件严禁直接实例化不受管的 Token |
| **执行控制 Checkpoint** | `Supervisor` (`supervisor.py`) | `Supervisor` | `Supervisor._save` (`SupervisorState`) | `CheckpointStore` (`JsonCheckpointStore`) | 跨自治任务重试/恢复生命周期 | `core/`, `runtime/`, `capabilities/` (Agent 完全无感知) |

## 当前实际所有权边界说明

1. **会话恢复的双阶段所有权流转**：
   * 会话恢复属于跨 Owner 协作，由上层 facade (`MetaAgent._restore_core_session` / `CodingSessionBackendAdapter.resume`) 显式协调：
     1. `SessionRuntime.load(session_id)` 从 JSONL 产出不可变的 `SessionRestoreState`。
     2. Facade 调用 `ProviderController.restore_configuration(model, thinking_level)` 恢复配置。
     3. Facade 调用 `AgentRuntime.restore(state)` 将 canonical messages 回放至 `ConversationRuntime`。
2. **ContextManager 的不可变准备语义**：
   * `ContextManager.prepare()` 在派生 Provider 输入时通过 `project_messages()` 进行深拷贝，裁剪/摘要/注入 `<agent-state>` 绝不改写 `ConversationRuntime` 中的权威活跃消息列表。
3. **Provider 状态只读投影机制**：
   * `ProviderConfigurationProjection` 仅持有权威 `ProviderState` 的引用，不包含任何可写方法或 Controller 引用；Controller 在提交状态更新后主动调用 `_sync()` 刷新引用。
