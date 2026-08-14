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
| **Kernel** | Agent Loop / Turn / Session 语义、Canonical Conversation、Provider Port、ToolCall protocol、Context Window / Compaction / projection、Cancellation、Usage / Budget、Event Stream | read/write/edit/bash、MCP、Memory、Plan、Skill、SubAgent、Autonomy、Dream、Learning |
| **Harness** | ProviderManager、ToolRegistry、ToolRuntime、Middleware、Permission、ExecutionBackend/Sandbox、SessionRepository、SessionRecorder、Trace/Event Sink | 具体 Coding Tool、能力路由 |
| **Capability** | Skill、MCP、Plan、Memory、SubAgent、Browser、ComputerUse | Agent 引擎门面（agent、agent_runtime） |
| **Supervisor** | Autonomy、Scheduler、Checkpoint、Retry/Goal lifecycle、Dream、Learning | Agent 内部私有对象访问 |

### 1.3 Kernel 边界规则（契约化）

- Kernel 可认识 ToolCall，但不得 import 具体 Coding Tool（tooling/builtin、tooling/internal、tooling/mcp）。
- Kernel 可认识 Session 语义，但不得依赖 SessionRepository / JsonlSessionStorage / SessionRecorder。
- Kernel 可调用 Provider Port（协议），但不得绑定 ProviderManager / 具体 provider。
- Kernel 的 Event Stream 必须能被 Supervisor 订阅，且暴露的仅是契约事件，不是 `Agent._xxx` 私有字段。

## 2. 生产模块 → 层映射（已核实）

| 层 | 当前模块 | 说明 |
|---|---|---|
| **Kernel** | `lion_code/core/`（loop, conversation, messages, events, provider_events, provider, tools, types, cancellation, session/） | Loop/Turn/Session/ToolCall/Provider Port/Cancellation |
| **Kernel（部分）** | `lion_code/context/`（limits, estimator, projector, policy, compaction, manager） | Context Window / Compaction 原型 |
| **Harness** | `lion_code/composition/`、`provider_manager.py`、`providers/`、`tooling/`、`agent_runtime.py`（LionAgentRuntime）、`session_runtime/`、`application/`（部分）、`observers/` | Provider/ToolRuntime/Middleware/SessionRecorder/Event Sink |
| **Capability** | `capabilities/`、`memory_runtime/`、`session_memory*.py`、`plan_runtime.py`、`subagent_runtime.py`、`subagent_factory.py`、`skill_runtime.py`、`mcp_client.py` | Skill/MCP/Plan/Memory/SubAgent |
| **Supervisor** | `autonomy_runtime.py`、`dream*.py`、`dream_adapter.py`、`learning_runtime.py` | Autonomy/Dream/Learning |
| **Facade** | `agent.py`、`application/` | Agent 门面 + 应用端口（门面组装各层，不属于任何一层） |

> 注：`agent.py` / `composition/agent_builder.py` 是门面与 Composition Root，把 Foundation /
> Provider / Capability / Tooling / Coordinator / Session 一次性组装；它不是 Kernel。

## 3. 测试目录/文件 → 层映射

来源与单一权威：**`tests/OWNERSHIP.md`**（schema `test-ownership/v1`）。映射只重定义归属，
不移动、不删除任何测试文件。

| 测试目录/文件（归约） | Layer | 备注 |
|---|---|---|
| tests/core/、tests/context/、tests/providers/、test_usage.py、test_agent_run.py、test_model_query.py | kernel | Kernel 契约测试 |
| tests/adapters/、tests/session_runtime/、tests/runtime/、tests/tooling/（大部）、tests/application/（facade）、test_hooks.py、test_provider_manager.py、test_project_identity.py、test_prompt.py、tests/tui/（大部） | harness | Harness 契约测试 |
| tests/capabilities/、tests/memory_runtime/、test_plan_runtime.py、test_mcp_client.py、test_session_memory*.py、application/test_skill_commands.py、tests/tooling/（skill/subagent/mcp/plan-tools 文件） | capability | Capability 契约测试 |
| test_autonomy*.py、test_dream.py、test_learning.py、integration/test_application_coding_session.py + application/test_coding_session_ports.py（overflow-retry 部分） | supervisor | Supervisor 契约测试 |
| tests/tui/test_tui_app.py、test_cli.py | product | 完整应用集成 |
| tests/architecture/、tests/benchmarks/、test_context_formal_benchmark.py、test_quality_baseline.py | eval | 门禁/评测/质量工具（层外） |
| tests/tooling/、tests/integration/、tests/memory_runtime/（test_core_integration）、tests/application/（test_coding_session_ports） | mixed | 跨层；混合文件按文件标注主层 |

## 4. 归属声明：`<relevant-memory>` / Plan reset / MCP / SubAgent 是 Capability

以下行为**不得**定义为 Kernel / Core Runtime 必须行为，其测试归 **capability**：

- `<relevant-memory>`：由 `memory_runtime/injector.py::MemoryContextInjector._format` 产生，
  是 **Memory Capability**。相关测试：`tests/memory_runtime/test_injector.py`、
  `tests/memory_runtime/test_core_integration.py`。
- **Plan reset**（`apply_plan_context_reset`、`PlanRuntime.reset_*`）：位于 `plan_runtime.py`
  与 chat 编排中，是 **Plan Capability** 行为。相关测试：`tests/test_plan_runtime.py`、
  `tests/tooling/test_agent_runtime.py`（plan-mode 部分）。
- **MCP**：`capabilities/mcp.py` + `mcp_client.py`，是 **Capability**。相关测试：
  `tests/test_mcp_client.py`、`tests/tooling/test_mcp_adapter.py`、
  `tests/tooling/test_tool_environment.py`。
- **SubAgent / Skill**：`subagent_runtime.py`、`skill_runtime.py`，是 **Capability**。
  相关测试：`tests/tooling/test_capability_runtimes.py`、`tests/tooling/test_tool_selection.py`、
  `tests/tooling/test_skill_registry_view.py`、`tests/tooling/test_agent_internal_runtime.py`（部分）。

"core runtime 必须行为"措辞废弃，替换为 **Kernel 不变量**。

## 5. "不是 Kernel" 边界清单

以下符号/行为在真实代码中属于 Kernel 之外；Kernel 契约不覆盖它们：

- read/write/edit/bash 具体工具 → Harness（tooling/builtin）
- ToolRegistry / ToolRuntime / Middleware / Permission / ExecutionBackend → Harness（tooling/）
- ProviderManager / providers / SessionRepository / SessionRecorder / JsonlSessionStorage → Harness
- TerminalRenderer / UsageObserver（trace/event sink）→ Harness（observers/）
- MCP、Skill、SubAgent、Plan、Memory（含 `<relevant-memory>`）→ Capability
- Autonomy、Scheduler、Retry/Goal lifecycle、Dream、Learning → Supervisor
- `/dream`、`/learn`、`/handoff`、`/session-memory` 命令编排 → Capability/Supervisor（按符号归属）

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
