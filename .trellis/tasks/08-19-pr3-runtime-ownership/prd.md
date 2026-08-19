# PR3: Runtime Ownership + Provider Dependency DAG

## 背景

PR1（Runtime Boundary）建立了 `lion_code/runtime` 物理边界，PR2（Profile/Config/RuntimeBindings 三轴分离）
整理了 Composition Root 输入。本 PR 是本轮架构治理的核心：消除 Deferred binding 暴露的
semantic/object-graph cycle，把 Runtime 收敛成三个单一职责 Owner + 一个纯编排层。

## 问题

1. **Provider ↔ Runtime 对象环**：`AgentRuntimeCoordinator` 构造时持有 `ProviderManager`，
   `ProviderManager` 通过 `DeferredProviderRuntimePort` / `DeferredModelContextControl` /
   `DeferredBackgroundScheduler` / `SessionRecorderConfigurationRecorder` 在 coordinator
   构造完成后 bind 回 coordinator。Port 解决了 import coupling，但对象图上仍是环。
2. **AgentRuntimeCoordinator 职责过重**：同时编排 Core run、拥有 context 压缩状态、
   observer 装配、run 输出捕获、后台任务集合。
3. **SessionLifecycle 只是 coordinator 的 friend class**：直接访问
   `coordinator._identity` / `_session` / `_runtime` 私有字段，且 `restore` 内部调用
   `coordinator.provider_manager.restore_configuration()`，把环延伸进 session 恢复路径。
4. **AgentComposition 是 flat bag**：20 个平铺字段无层级。

## 目标

Runtime 收敛为：

```
AgentRuntime              —— 只编排一次 Agent operation 中各 Owner 的调用顺序
├── ConversationRuntime   —— AgentHarness / canonical active messages / live provider+model /
│                            prompt/continue / steer/follow-up / current run capture /
│                            cancellation bridge / tool execution bridge / event subscriptions /
│                            retired provider 异步关闭
├── SessionRuntime        —— SessionIdentityState / SessionRepository / SessionRecorder 生命周期 /
│                            new / load(→immutable SessionRestoreState) / restore / close /
│                            Provider 配置变更窄端口（record_configuration_change）
└── ContextRuntime        —— ContextManager / ContextCompactor / ModelLimitsResolver+cache /
                             effective_window / prepare context / compaction decisions+state
```

Provider 侧：`ProviderManager` 更名 `ProviderController`（职责吻合：owns ProviderState、
builds Provider、配置命令），只命令 Conversation/Context/Session 三个 Runtime：
- → ConversationRuntime：`replace_provider` / `set_model` / `retire_provider` / `is_running`
- → ContextRuntime：`replace_context_compactor` / `invalidate_model_limit_cache`
- → SessionRuntime：`record_configuration_change`（窄 recorder port）

禁止 `AgentRuntime ↔ ProviderController` 任何方向引用；禁止 `Deferred*` 存在。

Runtime 不通过 ProviderController 查询 current model/provider/context limits：
模型与 Provider 来自 ConversationRuntime live state，限制缓存来自 ContextRuntime。

## Session restore

改为显式跨 Owner 编排（facade 层）：

```
state = SessionRuntime.load(session_id)          # immutable SessionRestoreState
ProviderController.restore_configuration(model=state.model, thinking_level=state.thinking_level)
AgentRuntime.restore(state)
```

不得给 SessionRuntime 注入回指 ProviderController 的 callback。

## 必须删除

- `DeferredProviderRuntimePort`、`DeferredModelContextControl`、`DeferredBackgroundScheduler`
- `SessionRecorderConfigurationRecorder`（其职责并入 SessionRuntime 窄端口）
- `SessionLifecycle`（由真正的 SessionRuntime 取代）、`LionAgentRuntime`、`AgentRuntimeCoordinator` 旧名
- 不留 deprecated alias / compatibility class

## AgentComposition 分层

flat bag 改为有结构的 composition result：`runtime`（agent/conversation/session/context/
provider_controller/usage/budget）、`capabilities`（registry + product controls）、
`tooling`、`interaction`（notices/confirmation/status）。Composition 可以知道一切，
但不能返回没有层级的一切列表。

## 约束（禁止项）

- 不重写 Agent Kernel、不改变 AgentHarness loop 语义、不改变 canonical event stream
- 不增加第二份 message history / 第二个 Session writer / 不复制 Context 状态给多个 Owner
- 不引入 ServiceLocator、不用大量 callback 隐藏对象环、不用 Optional[Any]/动态属性绕过所有权

## 验收标准

1. 新增架构测试证明：AgentRuntime 不持有 ProviderController；ProviderController 不持有
   AgentRuntime；三个 Deferred 类型不存在；SessionRuntime 不访问 AgentRuntime 私有字段；
   ContextRuntime 是 compaction mutable state 唯一 owner；ConversationRuntime 是
   active Provider/messages/Harness 唯一 owner；SessionRuntime 是 session lifecycle/recorder
   唯一 owner；runtime 包无 Application/TUI 反向依赖。
2. provider / session restore / context compaction / event stream / composition / MetaAgent
   测试与全量测试套件通过；ruff / import gates / 质量门禁通过。
3. 交付物：改前 object graph、改后 DAG、三个 Owner 的状态清单、Provider 切换数据流、
   Session restore 数据流、删除的 Deferred 类型清单、AgentComposition 新结构、测试结果。
