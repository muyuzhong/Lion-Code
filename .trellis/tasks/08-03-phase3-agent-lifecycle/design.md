# Agent Lifecycle 提取设计

## Boundary

`AgentLifecycle` 只协调 Provider 配置与 Thinking 状态：它解析目标配置，构建 replacement
Provider，并在成功后更新既有 Core Runtime、compactor、Memory query service 和 Session
recorder。`Agent` 继续拥有字段、Core Runtime、MemoryCoordinator 与 background-operation
队列，避免形成第二套运行时状态。

```text
Agent public API / internal restore path
             |
             v
      AgentLifecycle
       |          |
       |          +-- host._create_provider() -> lion_code.agent.create_provider
       v
Core replace_provider / set_model
       |
       +-- compactor + Memory query service refresh
       +-- host._schedule_background_operation(old_provider.aclose / recorder writes)
```

## Host Contract

`AgentLifecycleHost` 仅声明实际需要的配置字段和能力：当前 API/Thinking 字段、
`is_processing`、Core Runtime、MemoryCoordinator、SessionRecorder、缓存字段、
`_create_provider()` 以及 `_schedule_background_operation()`。它不接收完整 `Agent` 类型，
也不向 `Agent` 反向导入。

`Agent._create_provider(**kwargs)` 是刻意保留的薄 factory：它在调用时读取
`lion_code.agent.create_provider`，因此现有针对该路径的 patch 对构造、API 热切换和
Thinking 重建仍生效。

## Atomicity and Resource Rules

1. 先解析 target 配置并构建 replacement Provider/附属服务。
2. 构建抛错时不写 host 字段、不替换 Core Provider、不调度关闭。
3. 成功后原位替换 `LionAgentRuntime` 的 Provider，保留其 canonical messages。
4. 之后一次性更新配置、模型限制缓存、compactor 和 query service。
5. 旧 Provider 只经既有 background-operation 队列关闭；配置变更仍经既有 recorder 调度。

## Compatibility

- `Agent` 对外保留 `api_configured`、`get_api_config()`、`configure_api()`、
  `set_thinking()`、Thinking properties/setter/cycle。
- Session restore 改调生命周期对象的 Thinking 重建入口，不重复持久化历史 entry。
- `_child_api_kwargs()` 保持在 `Agent`，直接读取已更新的父级配置，避免改变
  `SubagentFactoryHost` 合同。

## Deferred

终端观察器的订阅/取消订阅与全局 shutdown 的资源顺序留给最终 `agent_runtime` 协调切片；
它们与 Provider 配置不共享足够的单一职责，当前拆出会扩大 Host 协议并破坏测试 patch 边界。
