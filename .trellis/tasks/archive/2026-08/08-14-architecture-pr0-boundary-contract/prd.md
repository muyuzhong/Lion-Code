# PR0 四层架构 Contract 固化（Kernel/Harness/Capability/Supervisor）

## Goal

Lion-Code（repo: muyuzhong/Lion-Code，branch master）正从当前 Full Agent 架构重构为：

```
Agent Kernel + Harness Runtime + Capability Plane + Supervisor Plane
```

本 PR0 **只固化架构 Contract 与测试分类**，不改造生产对象图、不创建新目录体系、不提前实现 build_meta_agent()。

### 核心原则

1. Kernel 只包含所有 Agent 都必须具备的不变量。
2. Harness Runtime 负责 Agent **如何运行**，而不是 Agent 有什么高级能力。
3. Capability 是可完全移除的可选能力。
4. Supervisor 控制跨 Turn / Session / Agent 的长期行为。
5. zero-extension、甚至 zero-tool Agent 必须是合法状态。
6. 禁止通过 Optional、Null Object、Deferred Feature Port 假装解耦。

## 背景与现状核实（2026-08-14）

规划前已核实仓库真实状态，关键事实：

- 本地 master 落后 origin/master，已合并最新 #27（`Muyuzhong/agent composition root`，02:50 的图分解版），代码文件已与 origin 完全同步。
- 代码库已经存在大量分层产物：`lion_code/core/`（Kernel 候选）、`lion_code/composition/`（composition root）、`lion_code/capabilities/`、`lion_code/tooling/`、`lion_code/providers/`、`lion_code/application/`、`lion_code/tui/`，以及 `autonomy_runtime.py`/`dream*.py`/`learning_runtime.py`（Supervisor 候选）。
- 现有 spec `.trellis/spec/backend/runtime-boundaries.md` 已深入描述 Core/Provider/Capability/State-Ownership 边界，但**未用 Kernel/Harness/Capability/Supervisor 四层词汇**。
- 事件流已分层：`core/events.py`（AgentEvent）+ `core/provider_events.py`（AssistantMessageEvent）+ `application/events.py`（SessionOwnEvent，含 CompactionStart/End）。
- `<relevant-memory>` 是 Memory 能力（`memory_runtime/injector.py` 的 `MemoryContextInjector._format`），当前被当作 runtime 行为测试。
- `apply_plan_context_reset` 位于 `agent_runtime.py` 的 chat 流程，是 Plan 能力行为。
- 现有架构门禁：`tests/architecture/_boundaries.py` + import-linter + AST 测试（test_runtime_boundaries / test_application_ports / test_tool_routing / test_composition_root）。

## Requirements

### R1. 固化四层边界定义

明确以下四层边界，作为本 PR 的可执行 Contract：

**Agent Kernel** 仅包括：
- Agent Loop
- Turn / Session semantics
- Canonical Conversation
- Provider Port
- Tool Call protocol
- Context Window
- Compaction
- Cancellation
- Usage / Budget semantics
- Event Stream contract

约束：
- Kernel 可以认识 ToolCall，但不能认识具体 Coding Tool。
- Kernel 可以认识 Session，但不能因此依赖 SessionRepository。
- Kernel 可以调用 Provider Port，但不能绑定具体 ProviderManager 实现。

**Harness Runtime** 包括：
- ProviderManager / Provider Router
- ToolRegistry
- ToolRuntime
- Middleware
- Permission / Safety
- ExecutionBackend
- Sandbox
- SessionRepository
- SessionRecorder / Persistence
- Trace / Event Sink

**Capability Plane** 包括但不限于：
- Skill、MCP、Plan、Memory、SubAgent、Browser、ComputerUse

**Supervisor Plane** 包括：
- Autonomy、Scheduler、Checkpoint orchestration、Retry / Recovery、Goal lifecycle、Dream、Learning、Long-running task orchestration

### R2. 关键修正（不要误判 Kernel Contract）

以下内容**不是 Kernel**：
- read/write/edit/bash 等 Coding Tools
- MCP、Memory、Plan、Skill、SubAgent
- Autonomy、Dream、Learning

尤其需要**重新分类当前所谓 core runtime 测试**。`<relevant-memory>`、Plan reset、MCP、SubAgent 等不能再被定义为 Core Runtime 必须行为。

### R3. Event Stream 加入 Kernel contract

至少从架构上允许表达以下事件：
- TurnStarted、ModelStarted、ModelDelta、ToolCallRequested、ToolCallCompleted
- CompactionStarted、CompactionCompleted、TurnCompleted、TurnFailed、Cancelled

本 PR 不要求立刻实现完整事件系统，但必须避免未来 Supervisor 依赖 Agent 内部私有对象。

### R4. 新增可执行架构门禁

使四层边界尽可能由代码验证，而不是只写文档。

### R5. 禁止事项

本 PR：
- 不新增 NullMemory / NullPlan / NoopCapability
- 不新增 ServiceLocator / CapabilityContext
- 不提前 build_meta_agent()
- 不进行大规模目录搬迁
- 不为了保持旧 Feature 新增 Feature-specific Protocol
- 不删除现有 Full Product 行为测试，只重新定义其架构归属

## Acceptance Criteria

1. 明确哪些测试属于 Kernel contract、Harness contract、Capability / Product integration、Supervisor。
2. `<relevant-memory>`、Plan reset、MCP、SubAgent 等**不能再被定义为 Core Runtime 必须行为**（在 spec / 测试归属 / 门禁中体现）。
3. Event Stream 契约以代码可验证的方式加入 Kernel（至少允许表达 R3 的 10 个事件）。
4. 新增或调整可执行架构门禁，使四层边界由代码验证。
5. 不违反 R5 禁止事项。
6. 现有 Full Product 行为测试保持通过（只重定义归属，不删除行为）。

## 完成后需总结

- 实际发现的架构边界
- 修改内容
- 新增/调整的架构测试
- 是否发现原方案与真实代码不一致
- 下一 PR（Memory Runtime hard-chain removal）需要处理的真实入口

## 任务图

父任务只拥有需求集、任务图、跨 child 验收与最终集成评审，不承担实现。

| Child | 交付物 | 独立验证 |
|---|---|---|
| 08-14-pr0-boundary-audit | 边界审计 + 测试重新分类 | 归属清单落地，core runtime 测试重分类 |
| 08-14-pr0-event-stream-contract | Event Stream Kernel Contract | 事件契约可验证，避免 Supervisor 依赖私有对象 |
| 08-14-pr0-architecture-gates | 架构门禁测试 | 四层边界由代码验证 |

依赖顺序（写在各 child 文档中）：boundary-audit 先做（产出归属清单），event-stream 与 gates 可并行，但 gates 的"四层边界"定义引用 boundary-audit 的归属结论。

## 跨 Child 验收标准

- 三 child 合并后，`<relevant-memory>`/Plan reset/MCP/SubAgent 的测试不再归类于 Core Runtime 必须行为。
- Kernel 事件契约（R3 的 10 事件）有代码级声明或测试。
- 四层边界有 import/AST 级门禁，且现有全部测试通过。
- 无 R5 禁止的占位解耦（Null/Noop/ServiceLocator/CapabilityContext）。

## Notes

- 复杂的任务必须有 prd/design/implement 才可 start。子任务各自写 prd/design/implement。
- 参考现有 `.trellis/spec/backend/runtime-boundaries.md` 与 `tests/architecture/_boundaries.py`，避免重复或冲突。
