# PR0 四层架构 Design（Kernel / Harness / Capability / Supervisor）

本 design 是三个 child 的共享技术设计。它把 PR0 的四层 Contract 落到当前真实代码上，并定义测试分类框架、事件契约与门禁策略。child 设计引用本文件，不重复定义。

## 1. 现状映射（已核实）

### 1.1 生产代码 → 层候选

| 层 | 当前模块（候选） | 说明 |
|---|---|---|
| **Kernel** | `lion_code/core/`（loop, conversation, messages, events, provider_events, provider, tools, types, cancellation, session/） | 已有 Loop/Turn/Session/ToolCall/Provider Port/Cancellation 原型 |
| **Kernel（部分）** | `lion_code/context/`（limits, estimator, projector, policy, compaction, manager） | Context Window / Compaction 原型 |
| **Harness** | `lion_code/composition/`、`provider_manager.py`、`providers/`、`tooling/`、`agent_runtime.py`(LionAgentRuntime)、`session_runtime/`、`application/`（部分） | Provider/ToolRuntime/Middleware/SessionRecorder/Event Sink |
| **Capability** | `capabilities/`、`memory_runtime/`、`session_memory*.py`、`plan_runtime.py`、`subagent_runtime.py`、`mcp_client.py` | Skill/MCP/Plan/Memory/SubAgent |
| **Supervisor** | `autonomy_runtime.py`、`dream*.py`、`learning_runtime.py` | Autonomy/Dream/Learning |
| **Facade** | `agent.py`、`application/` | Agent 门面 + 应用端口 |

> 注意：以上是"候选"，不是结论。child 08-14-pr0-boundary-audit 的职责就是核实并产出最终归属，尤其要确认 `core/` 里是否有混入 Harness/Capability 内容。

### 1.2 现状事实（影响设计的关键点）

- `build_agent_composition()`（composition/agent_builder.py）已存在，是**一次性 Composition Root**，把 Foundation/Provider/Capability/Tooling/RuntimeCoordinator/Session 全部组装。它不是"build_meta_agent"，PR0 不新增 meta-agent builder。
- **当前 Composition Root 把 Capability 与 Supervisor 硬编进 runtime**：`_build_capability_graph` 构建 MCP/Skill/SubAgent/Plan capability 并注册；`_build_session_graph` 构建 Dream/Autonomy/Learning。这是"Full Agent"装配现状，PR0 只固化为"装配契约"，不改生产对象图。
- 事件流已分层但归属未契约化：
  - `core/events.py`：AgentEvent（agent_start/end、turn_start/end、message_*/tool_execution_*）
  - `core/provider_events.py`：AssistantMessageEvent（text_/thinking_/toolcall_ 流事件）
  - `application/events.py`：SessionOwnEvent（session_agent_end、agent_settled、compaction_start/end、auto_retry_*、session/provider/thinking changed）
  - **gap**：Kernel 层没有显式 TurnFailed / Cancelled / CompactionStarted-Completed 契约事件（compaction 事件只在 application 层）。
- `<relevant-memory>` 由 `memory_runtime/injector.py::MemoryContextInjector._format` 产生，是 **Memory Capability**，不是 Kernel。
- `apply_plan_context_reset` 位于 `agent_runtime.py` 的 chat 编排中，是 **Plan Capability** 行为，不是 Kernel 不变量。
- 现有门禁 `tests/architecture/_boundaries.py` 是 **import 方向 + AST 模式** 双通道，但边界是 "core/providers/application/tui/capabilities" 旧词汇，未覆盖 Kernel/Harness/Capability/Supervisor 四层。

### 1.3 原方案 vs 真实代码的偏差（设计须处理）

| 原方案假设 | 真实代码 | 影响 |
|---|---|---|
| "从 Full Agent 重构" | 已大量分层（composition root、capabilities、narrow ports） | PR0 实际是**契约化既有分层**，而非从零分层 |
| "不提前实现 build_meta_agent()" | 已有 `build_agent_composition()` 一次性装配 | 需在契约中澄清两者边界；PR0 不新增装配 |
| Event Stream 从无到有 | 已有 core/application 双层事件 | 只需补 Kernel 层缺失事件 + 契约化归属 |
| "core runtime 测试" 是核心 | 部分 core runtime 测试实际测 Capability/Supervisor 行为 | 归属清单需重分类这些测试 |

## 2. 四层边界 Contract（规范性定义）

### 2.1 依赖方向

```
Supervisor ──► Capability ──► Harness ──► Kernel
    │              │              │
    └──────────────┴──────────────┴──► 均不反向依赖
```

- Kernel 不依赖 Harness/Capability/Supervisor/Application/TUI。
- Harness 依赖 Kernel；可被 Capability/Supervisor 依赖，但不依赖它们。
- Capability 依赖 Kernel 抽象 + Harness 的窄端口；不依赖 Agent 引擎门面（已有 `capabilities 不依赖 agent` 门禁）。
- Supervisor 依赖 Kernel 事件契约 + 窄端口；不得依赖 Agent 内部私有对象（靠 Event Stream 契约实现）。

### 2.2 Kernel 边界规则（契约化）

- Kernel 可认识 ToolCall，但不得 import 具体 Coding Tool（tooling/builtin、tooling/internal、tooling/mcp）。
- Kernel 可认识 Session 语义，但不得依赖 SessionRepository / JsonlSessionStorage / SessionRecorder。
- Kernel 可调用 Provider Port（协议），但不得绑定 ProviderManager / 具体 provider。
- Kernel 的 Event Stream 必须能被 Supervisor 订阅，且暴露的仅是契约事件，不是 `Agent._xxx` 私有字段。

### 2.3 现有 `tests/architecture/_boundaries.py` 的旧边界 → 四层词汇对照

现有契约 "Core 不依赖上层运行时包" 接近 "Kernel 不依赖 Harness"；但 `core` 目前是否干净需 child audit 确认（例如 `core/` 是否 import 了 `session_runtime` 或 `usage` 等）。child gates 负责把这些旧边界映射/扩展为四层，并保持 import-linter 与 `_boundaries.py` 一致。

## 3. Kernel Event Stream Contract（child 08-14-pr0-event-stream-contract 的输入）

PR0 要求至少能从架构上表达 10 个事件。映射到现状：

| 契约事件 | 现状 | gap |
|---|---|---|
| TurnStarted | `core/events.py::TurnStartEvent` ✅ | — |
| ModelStarted | `provider_events.py::AssistantStartEvent` / `AgentStartEvent`（需确认语义） | 命名/契约化 |
| ModelDelta | `provider_events.py::TextDeltaEvent`/`ThinkingDeltaEvent` ✅ | 契约化 |
| ToolCallRequested | `provider_events.py::ToolCallEndEvent` / `events.py::ToolExecutionStartEvent` | 契约化 |
| ToolCallCompleted | `events.py::ToolExecutionEndEvent` ✅ | — |
| CompactionStarted | 仅 `application/events.py::CompactionStartEvent` | Kernel 无 |
| CompactionCompleted | 仅 `application/events.py::CompactionEndEvent` | Kernel 无 |
| TurnCompleted | `events.py::TurnEndEvent` ✅ | — |
| TurnFailed | 无显式事件（error 走 AssistantErrorEvent / stop_reason） | Kernel 无 |
| Cancelled | 无显式事件（aborted 走 stop_reason） | Kernel 无 |

设计方向：在 `core/events.py` 增加/明确 Kernel 契约事件（至少 CompactionStarted/Completed、TurnFailed、Cancelled），**不要求立即全量实现**，但要有代码级声明与测试，保证 Supervisor 订阅的是契约而非私有对象。

## 4. 测试分类框架（child 08-14-pr0-boundary-audit 的输入）

按 4 层 + product integration 分类，产出一个**归属清单**（tests/ 下每个文件/目录 → 层）。分类判定规则：

- **Kernel**：被测对象在 Kernel 边界内，且不依赖 Harness/Capability/Supervisor 具体实现。判定：import 图中被测对象是否只触及 Kernel 模块。
- **Harness**：被测对象在 Harness 边界内（provider manager/router、tool runtime、middleware、permission、execution backend、session repository/recorder、event sink）。
- **Capability**：被测对象在 Capability 边界内（skill/mcp/plan/memory/subagent）。`<relevant-memory>`、Plan reset 相关测试应归 Capability。
- **Supervisor**：被测对象是跨 turn/session/agent 长期行为（autonomy/scheduler/checkpoint/retry/goal/dream/learning）。
- **Product integration**：多层组合端到端（如 full agent + TUI + 持久化）。
- **Mixed**：标注主层与混合原因；如测试同时测 Kernel 与 Harness 契约，拆分的成本高则记录"归属 = 主契约层"，并建议后续拆分。

分类落地方式（不删除行为）：优先用**目录/文件归属文档 + 测试文件头标注 + 必要时目录调整**。是否移动测试文件由 child 决定，但受 R5"不进行大规模目录搬迁"约束。

## 5. 架构门禁策略（child 08-14-pr0-architecture-gates 的输入）

在现有 `tests/architecture/_boundaries.py` + import-linter 基础上扩展：

1. **映射旧边界到四层词汇**：新增 Kernel/Harness/Capability/Supervisor 的 import 方向契约（如 `core` 不得 import `tooling`/`providers`/`session_runtime`/`usage`；`capabilities` 不得 import `agent`；Supervisor 不得 import 私有对象）。
2. **Event Stream 契约门禁**：Kernel 事件类型列表是契约；Supervisor 若订阅事件，只能引用 `core/events.py`/`core/provider_events.py` 的公开事件类型，不得触碰 `Agent._xxx`。
3. **"不是 Kernel"门禁**：断言 `core/` 不引用 `<relevant-memory>`/Plan/MCP/SubAgent/Autonomy/Dream/Learning 相关符号。
4. **zero-extension 合法性**：zero-tool / no-capability 装配是合法状态（门禁或测试）。

任何门禁扩展必须同步更新 `_boundaries.py` 与 `pyproject.toml` 的 import-linter 配置（现有 `test_import_linter_config_matches_boundaries` 强制二者一致）。

## 6. 与现有 spec 的关系

`.trellis/spec/backend/runtime-boundaries.md` 描述的是 Core/Provider/Capability/State-Ownership 的具体装配契约。PR0 引入的四层词汇**不推翻**这些细节，而是在其上增加**层归属**视图。PR0 完成后应在 spec 中补充"四层归属"章节或独立文档（child boundary-audit 产出的归属清单是其来源）。

## 7. 跨 child 依赖与集成

- 08-14-pr0-boundary-audit 先产出归属清单与 spec 更新。
- 08-14-pr0-event-stream-contract 与 08-14-pr0-architecture-gates 可并行；gates 的四层边界定义引用 audit 结论。
- 父任务最终集成评审：三 child 合并后跑全量测试 + import-linter + AST 门禁，验收跨 child 标准（见父 prd.md）。
