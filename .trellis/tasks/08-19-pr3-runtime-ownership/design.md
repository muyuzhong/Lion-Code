# Design: PR3 Runtime Ownership + Provider Dependency DAG

## 1. 修改前 object graph（经代码确认）

```
Composition Root (agent_builder.build_agent_composition)
│
├── AgentRuntimeCoordinator                          [runtime/agent.py]
│   ├── identity: RuntimeIdentityPort                [composition/ports.py]
│   │     （含 effective_window、_last_stop_reason、renderer 工厂、notices、api_configured）
│   ├── session: SessionStatePort                    [composition/ports.py]
│   │     （_session_state / _session_repository / tool_context 三样打包）
│   ├── execution: ExecutionControl
│   ├── usage: UsageLedger / budget: BudgetPolicy
│   ├── capabilities: CapabilityRuntime
│   ├── provider_manager: ProviderManager            ← coordinator 反向持有 Provider 面
│   ├── context_manager / context_compactor / model_limits_resolver
│   ├── _resolved_model_limits_for / _core_compaction_required
│   │   / _last_context_actions / _core_compaction_task      （context 状态散落）
│   ├── _background_tasks（Provider 关闭 + 配置 Entry 写入共用一个任务集）
│   ├── _output_buffer / _captured_assistant_text            （run 捕获）
│   ├── _terminal_renderer / _usage_observer / _session_recorder（observer 装配）
│   ├── _runtime: LionAgentRuntime                    （AgentHarness + live provider + messages）
│   └── _session_lifecycle: SessionLifecycle          [runtime/session_lifecycle.py]
│         （friend class：直接访问 coord._identity/_session/_runtime 私有字段；
│          restore 内调用 coord.provider_manager.restore_configuration → 环延伸进 restore）
│
└── ProviderManager                                  [runtime/provider.py]
    ├── state: ProviderState
    ├── runtime: DeferredProviderRuntimePort ──bind──→ AgentRuntimeCoordinator
    ├── context: DeferredModelContextControl ──bind──→ AgentRuntimeCoordinator
    ├── recorder: SessionRecorderConfigurationRecorder
    │                ──bind──→ (lambda: coordinator.session_recorder,
    │                             coordinator.schedule_background_operation)
    └── schedule_background_operation: DeferredBackgroundScheduler ──bind──→ coordinator
```

环：`AgentRuntimeCoordinator → ProviderManager → (四个 Deferred/适配器) → AgentRuntimeCoordinator`。
SessionLifecycle.restore 又调用 `provider_manager.restore_configuration`，使环在运行期被真实走过。

## 2. 修改后 DAG

构建顺序（Composition Root，全部构造期一次完成，无 bind 二段式）：

```
foundation（execution/usage/budget/session identity/repository/tooling/identity port）
 → ContextRuntime        （不需要 conversation）
 → ConversationRuntime   （prepare_context = context.prepare_context）
 → SessionRuntime        （initial recorder 用 config.model/config thinking 创建）
 → AgentRuntime          （编排三者；构造尾 reset_observers）
 → ProviderController    （构造时直接注入 conversation/context/session 三个端口）
```

```
MetaAgent / Agent (facade)
├── agent_runtime: AgentRuntime
├── provider_controller: ProviderController
├── session: SessionRuntime
└── usage / budget / permission_mode

AgentRuntime ──→ ConversationRuntime / SessionRuntime / ContextRuntime
             ──→ ExecutionControl / UsageLedger / BudgetPolicy / RuntimeIdentityPort
ProviderController ──→ ConversationRuntime (replace_provider/set_model/retire_provider/is_running)
                   ──→ ContextRuntime      (replace_context_compactor/invalidate_model_limit_cache)
                   ──→ SessionRuntime      (record_configuration_change)
SessionRuntime ──→ SessionIdentityState / SessionRepository / SessionRecorder / CapabilityLifecycle
ContextRuntime ──→ ContextManager / ContextCompactor / ModelLimitsResolver / UsageLedger(读快照)
ConversationRuntime ──→ AgentHarness / ToolRuntime / live ModelProvider
```

无 AgentRuntime ↔ ProviderController 边；无 Deferred*。

关键决策：

- **初始 Provider 构建脱离 Controller**：把 `ProviderManager._build_provider_for_state`
  提为模块级 `build_provider_for_state(factory, state, level)`；Composition Root 直接为
  `ProviderState(config)` 构建 initial provider（或用 bindings 注入的 provider），
  ConversationRuntime 先于 ProviderController 存在，Controller 构造时端口直连。
- **retired provider 关闭归 ConversationRuntime**：ProviderController 换 Provider 后调用
  `conversation.retire_provider(old)`；关闭任务集在 ConversationRuntime 内，
  `AgentRuntime.ensure_ready()` 每轮 flush（保持现有行为：chat 时旧 provider 已关闭）。
- **配置 Entry 写入归 SessionRuntime**：`record_configuration_change(previous, current)`
  是 SessionRuntime 的同步窄端口，内部 diff + 调度异步落盘；pending 写入在
  `ensure_ready / load / new_session / close` flush（保持现有顺序保证）。
  原 `SessionRecorderConfigurationRecorder` 的 diff 逻辑随迁。
- **effective_window / 模型限制缓存归 ContextRuntime**（原挂 identity port，属 context 派生态）。
- **`_last_stop_reason` 归 AgentRuntime**（run 结果投影态）。
- **RuntimeIdentityPort 瘦身**：保留 is_sub_agent / terminal_output / api_configured /
  renderer 工厂 / notices；effective_window、_last_stop_reason、is_aborted 移除。
- **SessionStatePort 删除**：SessionRuntime 直接拥有 session_state/repository/cwd。

## 3. 三个 Runtime Owner 的状态清单

| Owner | 拥有状态 | 主要操作 |
|---|---|---|
| ConversationRuntime | AgentHarness、live provider、active messages、steer/follow-up 队列、run 输出捕获 buffer、retired provider 关闭任务集 | prompt/continue/set_model/replace_provider/retire_provider/replace_active_context/cancel/steer/follow_up/subscribe/emit/flush/aclose |
| SessionRuntime | SessionIdentityState、SessionRepository、SessionRecorder（含 None for sub-agent）、CapabilityLifecycle 分发、配置 Entry 写任务集 | new_session/load→SessionRestoreState/restore/ensure_ready/record_compaction/context_entry_ids/record_configuration_change/close |
| ContextRuntime | ContextManager、ContextCompactor、ModelLimitsResolver、(provider id, model)→limits 缓存、effective_window、_last_context_actions、compaction_required、压缩任务句柄 | prepare_context/should_compact_now/summarize(跟踪压缩任务)/resolve_model_limits/replace_context_compactor/invalidate_model_limit_cache/on_session_reset/on_compacted |

AgentRuntime 自身状态：_last_stop_reason、observer 装配句柄（usage/recorder/renderer/capture
的 unsubscribe 列表）、run 超时控制。不再拥有 provider/context/session 的任何 mutable 状态。

## 4. Provider 配置切换数据流（以 configure(model, api_key) 为例）

```
ProviderController.configure(...)
  ├─ reject_if_running（conversation.is_running）
  ├─ _resolve_target_state → ProviderState
  ├─ provider 变更：build_provider_for_state(...) + ProviderContextCompactor(
  │      provider=新, get_model=lambda: conversation.model)   ← live state，不查 controller
  ├─ conversation.replace_provider(新) → 返回旧
  │   失败回滚：conversation.replace_provider(旧)+set_model(旧)+retire_provider(新)
  ├─ conversation.set_model(target.model)（仅 model 变更时）
  ├─ self._state = target
  ├─ provider 变更：context.replace_context_compactor(新 compactor)
  │                  context.invalidate_model_limit_cache(target.model)
  │   仅 model 变更：context.invalidate_model_limit_cache(target.model)
  ├─ session.record_configuration_change(previous_view, current_view)
  │      →（diff model/thinking）调度 recorder.record_model_change / record_thinking_level_change
  └─ conversation.retire_provider(旧) → 旧 provider aclose 任务入 conversation 任务集
       （下个 ensure_ready/状态边界 flush 收敛异常）
```

## 5. Session restore 数据流

```
MetaAgent.restore_core_session(session_id)            [facade 编排]
  ├─ state = session.load(session_id)
  │     （SessionRuntime：flush 配置写任务 → repository.load → None / SessionRestoreState）
  ├─ state is None → return False
  ├─ provider_controller.restore_configuration(
  │      model=state.model, thinking_level=state.thinking_level)   （record=False）
  │      内部经 conversation/context 命令生效；ProviderController 不被 SessionRuntime 反向触达
  └─ agent_runtime.restore(state)
        ├─ context.on_session_reset()
        ├─ conversation.replace_active_context(state.messages)
        ├─ session.restore(state)（身份 reset + 重建 recorder + capabilities.on_restore_session）
        ├─ agent_runtime.reset_observers()
        ├─ agent_runtime.ensure_ready()（conversation flush → context.resolve_limits →
        │    session.ensure_ready：flush + recorder.initialize）
        └─ usage reset + 通知 "Session restored (N messages)."
```

clear_history → `MetaAgent.new_session()`：facade 读 `provider_controller.view`
（model/thinking）作为 recorder 初始参数传入 `agent_runtime.new_session(model, thinking)`，
AgentRuntime 依次调用 session/conversation/context 的对应命令（AgentRuntime 不查 controller）。

## 6. AgentComposition 新结构

```
AgentComposition
├── runtime: RuntimeComposition
│   ├── agent / conversation / session / context / provider_controller
│   └── usage / budget
├── capabilities: CapabilityComposition
│   ├── registry / runtime(CapabilityRuntime)
│   └── plan / subagent_factory / subagent_executor / skill_runtime（product controls，可为 None）
├── tooling: ToolingComposition
│   └── registry / runtime(ToolRuntime) / context(ToolContext) / permission_policy / prompt_composer
└── interaction: InteractionComposition
    └── notices / confirmation / status_sink
```

## 7. 文件布局

- `runtime/conversation.py`（新，自 agent.py 拆出 + 捕获/retire 职责）
- `runtime/session.py`（新，取代 session_lifecycle.py + 真正持有状态）
- `runtime/context.py`（新，聚合 context 状态）
- `runtime/agent.py`（重写为纯编排 AgentRuntime + AgentRunResult + 瘦 identity 协议）
- `runtime/provider.py`（ProviderManager→ProviderController，端口对齐三个 Runtime）
- `runtime/session_lifecycle.py` 删除
- `composition/agent_builder.py`（新构建顺序 + 分层 AgentComposition）
- `composition/ports.py`（删 Deferred*×3 + SessionRecorderConfigurationRecorder +
  SessionStatePort；RuntimeIdentityPort 瘦身）
- `meta_agent.py` / `agent.py`（facade 重接线与 restore/new_session 编排）

## 8. 测试策略

- 新增 `tests/architecture/test_runtime_ownership.py`：10 项 object graph 断言
  （含 Deferred 符号缺失、AgentRuntime↔ProviderController 无引用、各 Owner 唯一性、
  runtime 包无 application/tui import）。
- 更新既有测试到新 API（test_provider_manager → ProviderController、
  test_agent_core_runtime 的内部属性访问、architecture/test_runtime_boundaries 中
  session_recorder 构造点与 usage 调用点清单）。
- 全量 unittest + CI 门禁（ruff/mypy/基线比对）。
