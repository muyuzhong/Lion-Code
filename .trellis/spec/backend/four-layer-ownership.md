# 四层归属（Kernel / Harness / Capability / Supervisor）

> 本契约定义 Lion Code 运行时的四层归属视图，是 [Runtime Boundaries](./runtime-boundaries.md)
> 与 [Capability SPI](./capability-spi.md) 之上的**层归属**视图，不推翻其中的具体装配契约。
> 由 PR0 边界审计产出；测试归属清单见 `tests/OWNERSHIP.md`。

## 1. 四层定义

### 1.1 依赖方向（规范性）

```
Supervisor ──► Capability ──► Harness ──► Kernel
    │              │              │
    └──────────────┴──────────────┴──► 均不反向依赖
```

- Kernel 不依赖 Harness/Capability/Supervisor/Application/TUI。
- Harness 依赖 Kernel；可被 Capability/Supervisor 依赖，但不依赖它们。
- Capability 依赖 Kernel 抽象 + Harness 的窄端口；不依赖 Agent 引擎门面
  （既有"capabilities 不依赖 agent"门禁，见 capability-spi.md）。
- Supervisor 依赖 Kernel 事件契约 + 窄端口；不得依赖 Agent 内部私有对象
  （靠 Event Stream 契约实现）。

### 1.2 层内容

| 层 | 契约内容 | 反例（不属于本层） |
|---|---|---|
| **Kernel** | Agent Loop / Turn / Session 语义、Canonical Conversation、Provider Port、ToolCall protocol、Context Window / Compaction / projection、Cancellation、Usage / Budget、Event Stream | read/write/edit/bash、Memory、Plan、Skill、SubAgent、Autonomy、Dream、Learning |
| **Harness** | ProviderManager、ToolRegistry、ToolRuntime、Middleware、Permission、ExecutionBackend/Sandbox、SessionRepository、SessionRecorder、Trace/Event Sink | 具体 Coding Tool、能力路由、Plan/Autonomy 产品模式（Permission 只负责通用安全语义，PR4） |
| **Capability** | Skill、Plan、Memory、SubAgent、Browser、ComputerUse | Agent 引擎门面（agent、agent_runtime） |
| **Supervisor** | Autonomy、Scheduler、Checkpoint、Retry/Goal lifecycle、Dream、Learning | Agent 内部私有对象访问 |

### 1.3 Kernel 边界规则（契约化）

- Kernel 可认识 ToolCall，但不得 import 具体 Coding Tool（tooling/builtin、tooling/internal）。
- Kernel 可认识 Session 语义，但不得依赖 SessionRepository / JsonlSessionStorage / SessionRecorder。
- Kernel 可调用 Provider Port（协议），但不得绑定 ProviderManager / 具体 provider。
- Kernel 的 Event Stream 必须能被 Supervisor 订阅，且暴露的仅是契约事件，不是 `Agent._xxx` 私有字段。

### 1.4 Kernel Event Stream 契约

`core/events.py`（`AgentEvent` union）+ `core/provider_events.py`（`AssistantMessageEvent` union）
是 Kernel 事件契约的权威源。契约至少允许表达以下 10 个事件（PR0 验收）：

| 契约事件 | Kernel 表达 | 状态 |
|---|---|---|
| TurnStarted | `TurnStartEvent` | 已发射 |
| ModelStarted | `AssistantStartEvent` | 已发射 |
| ModelDelta | `TextDeltaEvent` / `ThinkingDeltaEvent` | 已发射 |
| ToolCallRequested | `ToolCallEndEvent` / `ToolExecutionStartEvent` | 已发射 |
| ToolCallCompleted | `ToolExecutionEndEvent` | 已发射 |
| CompactionStarted | `CompactionStartedEvent` | 已发射（threshold/manual/overflow 的真实压缩执行点） |
| CompactionCompleted | `CompactionCompletedEvent` | 已发射（成功或取消；取消时 `aborted=True`） |
| TurnCompleted | `TurnEndEvent` | 已发射 |
| TurnFailed | `TurnFailedEvent` | 已发射（stop_reason="error"） |
| Cancelled | `CancelledEvent` | 已发射（stop_reason="aborted"） |

契约约束：

- Supervisor 订阅事件只能引用 `core/events.py` / `core/provider_events.py` 的公开类型，
  不得依赖 `Agent._xxx` 私有对象或 `AgentRuntimeCoordinator` 内部状态。
- 新增 Kernel 事件必须加入 `AgentEvent` / `AssistantMessageEvent` union 并带 discriminator，
  不得破坏既有事件的字段与判别值（Pi 兼容）。
- 契约测试：`tests/core/test_event_contract.py`（10 事件可表达、union round-trip、
  Kernel 事件模块无跨层 import、TurnFailed/Cancelled 真实发射）。

## 2. 生产模块 → 层映射（已核实）

| 层 | 当前模块 | 说明 |
|---|---|---|
| **Kernel** | `lion_code/core/`（loop, conversation, messages, events, provider_events, provider, tools, types, cancellation, session/） | Loop/Turn/Session/ToolCall/Provider Port/Cancellation |
| **Kernel（部分）** | `lion_code/context/`（limits, estimator, projector, policy, compaction, manager） | Context Window / Compaction 原型 |
| **Harness** | `lion_code/composition/`、`provider_manager.py`、`providers/`、`tooling/`、`agent_runtime.py`（LionAgentRuntime）、`session_runtime/`、`application/`（部分）、`observers/` | Provider/ToolRuntime/Middleware/SessionRecorder/Event Sink |
| **Capability** | `capabilities/`、`memory_runtime/`、`session_memory*.py`、`plan_runtime.py`、`subagent_runtime.py`、`subagent_factory.py`、`skill_runtime.py` | Skill/Plan/Memory/SubAgent |
| **Supervisor** | `autonomy_runtime.py`、`dream*.py`、`dream_adapter.py`、`learning_runtime.py` | Autonomy/Dream/Learning |
| **Facade** | `agent.py`、`meta_agent.py`、`application/` | Agent 门面 + 应用端口（门面组装各层，不属于任何一层） |

> 注：`agent.py` / `composition/agent_builder.py` 是门面与 Composition Root，把 Foundation /
> Provider / Capability / Tooling / Coordinator / Session 一次性组装；它不是 Kernel。

## 3. 测试目录/文件 → 层映射

来源与单一权威：**`tests/OWNERSHIP.md`**（schema `test-ownership/v1`）。映射只重定义归属，
不移动、不删除任何测试文件。

| 测试目录/文件（归约） | Layer | 备注 |
|---|---|---|
| tests/core/、tests/context/、tests/providers/、test_usage.py、test_agent_run.py、test_model_query.py | kernel | Kernel 契约测试 |
| tests/adapters/、tests/session_runtime/、tests/runtime/、tests/tooling/（大部）、tests/application/（facade）、test_hooks.py、test_provider_manager.py、test_project_identity.py、test_prompt.py、tests/tui/（大部） | harness | Harness 契约测试 |
| tests/capabilities/、tests/memory_runtime/、test_plan_runtime.py、test_session_memory*.py、application/test_skill_commands.py、tests/tooling/（skill/subagent/plan-tools 文件） | capability | Capability 契约测试 |
| test_autonomy*.py、test_dream.py、test_learning.py、integration/test_application_coding_session.py + application/test_coding_session_ports.py（overflow-retry 部分） | supervisor | Supervisor 契约测试 |
| tests/tui/test_tui_app.py、test_cli.py | product | 完整应用集成 |
| tests/architecture/、tests/benchmarks/、test_context_formal_benchmark.py、test_quality_baseline.py | eval | 门禁/评测/质量工具（层外） |
| tests/tooling/、tests/integration/、tests/memory_runtime/（test_core_integration）、tests/application/（test_coding_session_ports） | mixed | 跨层；混合文件按文件标注主层 |

## 4. 归属声明：`<relevant-memory>` / Plan reset / SubAgent 是 Capability

以下行为**不得**定义为 Kernel / Core Runtime 必须行为，其测试归 **capability**：

- `<relevant-memory>`：由 `memory_runtime/injector.py::MemoryContextInjector._format` 产生，
  是 **Memory Capability**。相关测试：`tests/memory_runtime/test_injector.py`、
  `tests/memory_runtime/test_core_integration.py`。
- **Plan reset**（`PlanRuntime.reset_*`）：位于 `plan_runtime.py`，是 **Plan Capability** 行为。
  `apply_plan_context_reset` 与 chat 编排中的 pending 特判已随 PR3 从 Kernel/Runtime 移除。相关测试：`tests/test_plan_runtime.py`、
  `tests/tooling/test_agent_runtime.py`（plan-mode 部分）。
- **SubAgent / Skill**：`subagent_runtime.py`、`skill_runtime.py`，是 **Capability**。
  相关测试：`tests/tooling/test_capability_runtimes.py`、`tests/tooling/test_tool_selection.py`、
  `tests/tooling/test_skill_registry_view.py`、`tests/tooling/test_agent_internal_runtime.py`（部分）。

"core runtime 必须行为"措辞废弃，替换为 **Kernel 不变量**。

> **PR1 → PR8 状态**：`AgentRuntimeCoordinator` 与 `SessionLifecycle` 仍然不认识
> Memory（没有 Memory 专属构造参数、符号或分支）。PR8 将原先删除的 turn 驱动行为
> 通过通用 Capability SPI 恢复：Full 图注册 `MemoryCapability`，由
> `TurnParticipant` 驱动快照/收尾、`ProjectionLayer` 生成临时 Provider 投影、
> `SessionParticipant` 处理 clear/restore，`AsyncCloseable` 回收召回任务。
> 因此 `<relevant-memory>` 不进入 canonical history 或 JSONL，Bare 图仍保持空
> capability registry；`tests/memory_runtime/test_core_integration.py` 的 7 个迁移测试
> 解除 skip 并验证真实行为。`SessionMemoryCoordinator` 只暴露 Memory capability
> 所需的窄方法与既有命令面；Dream 委托已随 PR7a 删除。

> **PR7a 状态**：Supervisor 对象（Autonomy/Dream/Learning 及其 model query）已从
> Composition Root、`Agent` facade 与 CLI/Application/TUI 产品路径移除。
> 独立 runtime 模块
> （`autonomy_runtime.py`、`dream*.py`、`learning_runtime.py`、`model_query.py`）保留
> 但无生产调用者，等待未来 Supervisor composition re-home；Agent 驱动的 Supervisor
> 行为测试统一以 `_REHOME` 原因 skip。

> **PR7b 状态**：外部工具协议（client、Capability、tool adapter 与共享 Tool
> Environment）已整体删除，不再作为产品、Composition 或测试的可达能力。
>
> **PR7c 状态**：组合选择由不可变 Profile 承载——`MinimalProfile`（Bare）、
> `CodingProfile`（Coding 工具形态 + 可选 Skill）、`FullProfile`（Coding 形态 +
> Memory/Plan/SubAgent/默认 Skill + 扩展 specs + 完整 Agent facade）。
> capability 集合 API 已删除，Feature branch 只在 Composition Root 的
> `_normalize_profile` 与各 `_build_*` 构造 helper（由架构测试强制）。

> **PR2 / PR6 / PR8 状态**：PR2 没有形成独立 PR，遗留的
> `ProviderManager -> MemoryQuerySink` 依赖由 PR6 直接删除，不保留 deferred sink、兼容层
> 或 fallback。PR8 让 `ProviderTextQueryService` 持有 Provider 对象或惰性工厂；Full
> Composition Root 传入 live provider accessor，因此 Provider replacement 后 side query
> 直接使用新 Provider，而不恢复 ProviderManager 通知链。PR6 同时提供 `build_meta_agent()`：空
> `CapabilityRegistry` 与空 `ToolRegistry` 都是可运行状态，Coding tools 只能由调用方显式
> 传入。`MetaAgent` facade 只暴露通用运行、对话、事件、上下文、会话、Provider、用量与
> 关闭契约，不暴露任何 Feature-specific API。

## 5. "不是 Kernel" 边界清单

以下符号/行为在真实代码中属于 Kernel 之外；Kernel 契约不覆盖它们：

- read/write/edit/bash 具体工具 → Harness（tooling/builtin）
- ToolRegistry / ToolRuntime / Middleware / Permission / ExecutionBackend → Harness（tooling/）
- ProviderManager / providers / SessionRepository / SessionRecorder / JsonlSessionStorage → Harness
- TerminalRenderer / UsageObserver（trace/event sink）→ Harness（observers/）
- Skill、SubAgent、Plan、Memory（含 `<relevant-memory>`）→ Capability
- Autonomy、Scheduler、Retry/Goal lifecycle、Dream、Learning → Supervisor
- `/handoff`、`/session-memory` 命令编排 → Capability/Supervisor（按符号归属）；
  `/dream`、`/learn`、`/goal`、`/loop` 已随 PR7a 从产品命令面删除

## 6. 与现有 spec 的关系（交叉引用）

- **[Runtime Boundaries](./runtime-boundaries.md)**：描述 Core/Provider/Permission/Session/Memory/
  Frontend 的具体装配契约。本契约在其上增加层归属视图，不推翻其细节。
  `tests/runtime/`、`tests/session_runtime/` 在 runtime-boundaries 中作为测试要求出现，
  本契约明确它们属 **Harness**，不是 Kernel "core runtime"。
- **[Capability SPI](./capability-spi.md)**：定义 Capability 扩展机制与 Kernel–Capability 分离。
  本契约的 Capability 归属声明与之一致：`capabilities` 不得 import `agent`/`agent_runtime`，
  Capability 工具经 ToolSource 构造时绑定窄 ToolCommand。
- **[Usage Ownership](./usage-ownership.md)**：Usage 单写者契约；本契约把 Usage/Budget 语义归
  **Kernel**（`tests/test_usage.py`、`tests/providers/test_model_limits.py` 等）。
- **测试归属清单**：`tests/OWNERSHIP.md` 是本契约第 3 节的单一权威数据源，二者保持一致。
