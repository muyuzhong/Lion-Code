# Agent Runtime Coordinator 设计

## Structure

不创建新的 runtime 模块。现有 `LionAgentRuntime` 保持为轻量的 Provider/Core Harness/
ToolRuntime 适配器；同一文件新增 `AgentRuntimeCoordinator`，负责更高层的单 Agent
Core 生命周期。

```text
Agent (composition root)
 ├─ AgentLifecycle        Provider / Thinking transaction
 ├─ SessionMemoryCoordinator / AutonomyRuntime / LearningRuntime
 ├─ ToolEnvironment + MCP discovery + tool routing
 └─ AgentRuntimeCoordinator
      └─ LionAgentRuntime  <-- only active Core messages / Provider
```

## State Ownership

`AgentRuntimeCoordinator` 拥有 Core-scoped state：`LionAgentRuntime`、observer
subscriptions、`UsageObserver`、`SessionRecorder`、terminal renderer、context compactor/
manager state、background operations、compaction task、output capture 和 run-result
bookkeeping。它通过兼容属性向 `Agent` 暴露 `_core_runtime`、`_session_recorder`、
`_usage_observer`、`_context_compactor` 等仍被前序切片使用的窄视图。

`Agent` 继续拥有模型/API 配置、工具与 MCP、Memory/Plan/Autonomy/Learning 协调、会话
repository、UI 回调与公开 API。这样 `AgentLifecycle` 仍可经 Agent 的兼容属性更新同一
Core Provider/compactor，而不会复制状态。

## Host Contract and Compatibility Anchors

`AgentRuntimeHost` 只声明 coordinator 实际调用的外部能力：系统提示词、工具运行时、
配置/预算/notice、MCP discovery、Session Memory 的轮前/轮后钩子、Plan reset、Session
repository、以及动态 renderer factory。

`Agent._create_terminal_renderer()` 在调用时读取 `lion_code.agent.TerminalRenderer`；
coordinator 通过此回调重建观察器，保留现有 patch anchor。`Agent` 的公开和高频私有
入口保留薄委托，避免调用者和测试改为穿透 coordinator。

## Turn and Session Invariants

1. 根 Agent 先完成一次 MCP 发现；失败只通知，不中断 Core 对话。
2. 每个用户轮：flush background → resolve limits → initialize recorder → compact → 固定
   Memory overlay → Core prompt/continue → usage/outcome → deterministic Session Memory
   update → rebuild next-turn overlays。
3. Context/Memory 只作为 Provider projection；Harness messages 和 JSONL 不包含 injected
   wrapper text。
4. clear/restore 复用同一 `LionAgentRuntime`，清空或替换其 active messages，绝不新建
   并行 history；Model/Thinking 恢复仍通过 AgentLifecycle。
5. close 使用 `try/finally` 链，任一关闭失败不能阻止后续 Memory/Core/MCP 资源回收。

## Migration Shape

先让 coordinator 构造 `LionAgentRuntime` 并提供 compatibility properties，再逐组迁移
Core methods，最后把 `Agent` 的方法改为委托。每完成一组均可由既有公共测试验证；不在
一个步骤中同时改变 context 数据、Provider 交换和 UI observer 语义。

## Deferred

Core Harness 的协议与 loop、ToolRuntime middleware、Memory/Autonomy/Learning 的业务逻辑
均为既有专属边界；S6 只调整它们的编排位置，不重写内部实现。
