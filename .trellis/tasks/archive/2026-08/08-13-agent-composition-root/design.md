# 技术设计：Agent Composition Root

## 1. 设计目标与边界

本轮只改变构造位置和依赖形状，不改变任何业务 use-case 的行为。`Agent` 保留
对外 facade 和兼容投影；一次性 object graph construction 进入
`lion_code.composition`。

Composition Root 是唯一知道所有 concrete runtime 的位置。它返回一个明确字段的
composition result，`Agent` 只显式接收/保存这些 facade 所需对象，不保存 Builder，
也不向 runtime/domain 暴露可查询的总容器。

## 2. 模块布局

```text
lion_code/
├── agent.py                         # public facade、旧 API 归一化与 delegates
└── composition/
    ├── __init__.py
    ├── config.py                    # AgentConfig / AgentDependencies
    ├── ports.py                     # composition-owned structural port adapters
    └── agent_builder.py              # 一次性 object graph construction
```

`ports.py` 只放为既有 Protocol 提供 structural implementation 的小适配器：
Runtime identity、Session state、Memory turn、Plan host、notice/confirmation、
MCP lifecycle flag 和 Provider 构造循环的 deferred port。它们不是 service
registry，也不向调用方按名称解析对象。

## 3. 配置与依赖契约

`AgentConfig` 使用 `@dataclass(frozen=True, slots=True)`，字段只表示用户/运行
输入：

- model、api key/base URL/provider kind input；
- permission mode、thinking、max cost/max turns；
- custom system prompt、custom tool selection；
- `is_sub_agent`、terminal output、MCP enablement。

`custom_tools` 在 Config 内规范化为 tuple，避免 frozen 外壳持有可变 list。

`AgentDependencies` 使用独立的 frozen slots dataclass，字段只表示外部提供的对象
或 test seam：session/session-memory repository、context manager/compactor、model
limit resolver、ToolRegistry/ToolEnvironment、Provider factory、hook/project
loaders、UI/renderer seam、confirm callback 和额外 Capability specs。默认值为
`None`/空 tuple，由 builder 在边界内补齐默认 concrete；不含 Config 字段，也不含
Builder、Agent 或任意 runtime graph。

旧 `Agent(...)` 参数在 facade 内转换成两份 dataclass。新 grouped 入口可直接给
`config=` 与 `dependencies=`；如果同一字段同时由旧参数和 grouped input 提供，
立即报错，避免隐式覆盖。

## 4. 构造顺序与循环处理

`build_agent_composition(config, dependencies)` 按以下顺序执行：

1. 创建 `PermissionController`、`SessionIdentityState`、`ExecutionControl`、
   `UsageLedger`、`BudgetPolicy`、read-file/MCP/interaction state。
2. 创建 `ToolEnvironment`/`ToolRegistry`（尊重 supplied instances、custom tool
   selection 和 root/child MCP ownership）。
3. 创建 Provider deferred ports 与 `ProviderManager(ProviderState, ...)`，按当前
   Config 构造初始 Provider；Provider factory 仍走 facade 注入的动态 wrapper，保留
   `patch("lion_code.agent.create_provider")` seam。
4. 创建窄 `PlanRuntimeHost` 与 `PlanRuntime`，创建 `SubagentFactory`、
   `SubagentExecutor`、`SkillRuntime`；子 Agent 读取 ProviderManager 的 live
   `ChildAgentConfig` projection，不持有父 Agent。
5. 注册默认 MCP/Skill/Subagent/Plan Capability 与依赖注入的额外 specs，聚合
   ToolSource 并写入 ToolRegistry，创建 `CapabilityRuntime`。默认注册只存在于
   builder。
6. 创建 `PromptComposer`、`ToolContext`、Permission/Hook/Result middleware 和
   `ToolRuntime`。ToolContext 继续只接收 `PlanView`、`PermissionView`、
   `CancellationView` 等窄端口；Auto classifier 使用一次性 deferred callback
   解决构造顺序，不绑定 Agent。
7. 创建 `RuntimeIdentityHost`、`SessionStateHost`、`MemoryTurnHost` 三个
   structural adapters，再创建 `AgentRuntimeCoordinator`。三个 adapter 只持有
   具体 state owner/coordination port，不持有 Agent。
8. 绑定 Provider deferred ports、查询 service、SessionRecorder configuration
   adapter 和 background scheduler；创建 `ProviderModelQuery`、
   `SessionMemoryCoordinator`、`DreamCoordinator`、`AutonomyRuntime`、
   `LearningRuntime`，最后绑定 deferred memory/classifier/snapshot holders。
9. 返回明确字段的 `AgentComposition`。`Agent` 解包后只提供 facade 属性和
   delegate 方法。

ProviderManager 与 Core/Session Memory 之间的现有构造环继续使用已有意义明确的
deferred structural ports；这些端口只解决 construction ordering，不提供对象查找
或通用 service access。

## 5. Agent facade 责任

保留：

- `prompt/chat/run/run_once`、conversation/session/compact/close；
- model/provider/thinking/permission/settings 投影；
- Plan controls、usage、goal/loop/learn/dream public entry；
- Application backend methods、历史兼容 private seam（如 `_core_runtime`、
  `_session_memory_coord`、`_mcp_initialized`）的显式 property/delegate。

移出：

- 所有 concrete runtime construction；
- 默认 Capability registration 和 tool source installation；
- Provider/Session/Memory/Plan/Runtime structural port assembly。

`Agent` 仍可保留少量 API 兼容 wrapper（例如 `_create_provider`、notice/confirm
入口），但这些 wrapper 只转发到 composition-owned seam，不再参与 object graph
构造。

## 6. Capability 扩展验收

用测试内的 `ExampleCapability` 提供一个只读 `ToolSource` 和可观察的 lifecycle
participant。测试通过 `AgentDependencies.extra_capabilities` 让 builder 注册它，
验证工具、prompt/session/lifecycle 贡献生效，并用源码快照/AST 断言新增 capability
不需要修改 `agent.py`、`agent_runtime.py`、`session_lifecycle.py`、
`tooling/context.py`、`application/` 或 `tui/`。

这证明新能力的修改面是：能力实现、Composition Root registration、测试；不是
通过 `Agent` 转发或 God Context 接入。

## 7. 兼容与回滚

- 旧 API 兼容通过 facade 的参数归一化，不保留第二套运行时实现。
- 既有动态 patch 点由 Agent module-level wrapper 注入 Dependencies；不把测试
  替身迁移到新的不可见路径。
- 构造顺序问题只允许使用命名明确的 deferred port；若验证失败，回滚点为本轮
  work commit，未触碰用户已有的 `.claude/`、`.codex/`、`.trellis/` dirty files。
- 不修改 Session JSONL、Provider state transaction、Capability SPI semantics 或
  Application/TUI contract。

## 8. 验证矩阵

| 层 | 验证 |
|---|---|
| Config/Dependencies | frozen、无 runtime object、旧参数等价、冲突输入明确失败 |
| Composition | 初始 Provider、ToolRegistry/Environment 注入、MCP root/child、默认 capability、deferred ports |
| Facade | public Agent、Application backend、Plan/usage/session/settings delegates |
| Runtime | Core loop、cancel/timeout、provider replacement、memory/dream/learning/autonomy |
| Extension | Example capability registration/lifecycle/tool/prompt/session |
| Architecture | no whole-Agent injection, no Builder retention, no Service Locator, constructor ownership |
| Quality | pytest、import-linter、architecture、ruff、mypy、compileall/diff check |
