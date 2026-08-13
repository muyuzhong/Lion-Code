# 提取 Agent Composition Root

## Goal

在前四轮解耦已经落地的 `master` 基础上完成最后一次纯架构收尾：把
Agent 的对象图构造和默认 Capability wiring 移到明确的 Composition Root，
使 `Agent` 收敛为 public API facade、Application Ports 的 structural
implementation，以及少量真正属于 Agent use-case 的 orchestration。

用户可观察的业务行为、CLI/TUI 入口、Application ports、Provider/Session/
Memory/MCP 生命周期和测试替身语义必须保持不变。

## 当前代码事实

- `ToolContext` 已经只有 session/cancellation/cwd/registry/permission/plan 等
  窄状态，没有 `controller` 字段。
- `AutonomyRuntime`、`LearningRuntime`、`SessionMemoryCoordinator`、
  `DreamCoordinator`、`SubagentFactory` 当前没有接收整个 `Agent`；已有
  `AgentRuntimeCoordinator` 的三组 Protocol 端口，但 `Agent.__init__` 仍把
  `self` 作为 `identity`、`session`、`memory` 传入。
- `Plan Capability` 已通过 `ToolSource`、`PromptLayer`、
  `SessionParticipant` 暴露扩展点，但 `PlanRuntime` 仍在
  `agent.py:379-383` 以 `PlanRuntime(self, ...)` 构造。
- `Agent.__init__` 当前在 `agent.py:321-569` 直接构造权限、工具、Provider、
  Runtime、Session Memory、Dream、Autonomy、Learning 和默认 Capability 图；
  `_register_capabilities` 位于 `agent.py:571-616`。
- `CapabilityRegistry` 明确不是 Service Locator；本轮不能引入
  `ServiceLocator`、`AgentContainer`、第三方 DI framework 或 Builder 查询 API。

## Requirements

### R1. 分离配置与外部依赖

- 新增 frozen、slots 的 `AgentConfig`，只包含用户/运行配置：model、Provider
  endpoint/config input、permission mode、thinking、budgets、sub-agent flag、
  terminal options、MCP enablement、custom system prompt 和 custom tool
  selection。
- 新增独立的 `AgentDependencies`，承载 repositories、context manager/
  compactor、model-limit resolver、supplied `ToolRegistry`/
  `ToolEnvironment`、Provider/hooks/project loader 等 test seams/factories 和
  可注入的额外 Capability spec。
- Config 不得保存 runtime object；Dependencies 不得演变成可按名称解析服务的
  God Config。

### R2. Composition Root

- 新增明确位置 `lion_code/composition/agent_builder.py`（及必要的 config/port
  支持模块），只负责按顺序构造 state owners、Provider state/factory、
  permission/session/execution/usage、tool registry/environment、domain
  runtimes、Capability registry/implementations、Tool runtime、Provider/Core
  runtime、runtime coordinator、Provider manager 和最终 wiring。
- Builder 采用一次性函数或一次性构造过程；构造完成后任何业务模块不得保存
  Builder。不得提供 `get()`、`resolve()`、`services[]` 等 Service Locator API。
- 默认 Capability composition 必须离开 `agent.py`；以后新增 Browser/Sandbox/
  Checkpoint 等能力只需修改 capability implementation、composition registration
  和测试。

### R3. Agent facade 与兼容性

- 保持现有 `Agent(...)` keyword 构造 API；允许通过新 Config/Dependencies
  入口表达同一构造图，但不得破坏旧参数、CLI、TUI、Application ports、子
  Agent、evaluation、Fake Provider、repository injection、custom tools/registry、
  MCP ownership 和既有 monkeypatch seams。
- `Agent` 构造函数不再直接构造大多数 domain/runtime concrete class；公共入口、
  settings/model/session/plan/usage/application backend 方法以 delegate 为主。
- 不借 Builder 隐藏未完成的前置解耦；如果前置条件测试失败，应先修正真实边界，
  不添加兼容层或 fallback。

### R4. 消灭剩余 whole-Agent/runtime injection

- `PlanRuntime(self)` 必须替换为实现 `PlanRuntimeHost` 的窄 structural port。
- `AgentRuntimeCoordinator(identity=self, session=self, memory=self)` 必须改为
  Composition Root 构造的窄 port 实现。
- 复查 `AutonomyRuntime(self)`、`LearningRuntime(self)`、
  `SessionMemoryCoordinator(self)`、`AgentLifecycle(self)`、`SubagentFactory(self)`；
  若仍存在，只能保留有明确理由的窄 structural port，并在最终报告逐项说明。
- Builder/runtime/domain 不得保存整个 `Agent` 或 Builder 引用。

### R5. 架构验收测试

- 增加 `SandboxCapabilityStub` 或 `ExampleCapability` 验收测试：新增 capability
  只修改 capability implementation、composition registration、tests，不修改
  `agent.py`、`agent_runtime.py`、`session_lifecycle.py`、`tooling/context.py`、
  `application/` 或 `tui/`。
- 增加静态/AST 边界检查：Builder 不被保存；不存在 Service Locator/AgentContainer；
  `Agent.__init__` 不直接构造大多数 domain runtime；Capability 仍只经既有 SPI
  进入工具、prompt、session lifecycle。

## Acceptance Criteria

- [ ] `AgentConfig` frozen 且不包含 runtime object；`AgentDependencies` 与 Config
      分离并覆盖 repository/tool/factory 注入。
- [ ] `Agent(...)` 旧 keyword API、CLI、TUI、Application ports、sub-agent、
      evaluation、Fake Provider、custom registry/environment、MCP ownership 和
      monkeypatch seams 全部保持可用。
- [ ] `agent.py` 不再直接构造大多数 domain/runtime concrete class；默认
      Capability wiring 在 Composition Root。
- [ ] 生产代码不存在 `PlanRuntime(self)`、`AgentRuntimeCoordinator(... self ...)`
      或其他 whole-Agent 注入；剩余例外有窄 Protocol 和测试证明。
- [ ] Example/Sandbox capability 验收测试通过，且新增 capability 不触碰用户列出的
      既有模块。
- [ ] Builder 不是 Service Locator，runtime/domain 不保存 Builder 或 Agent。
- [ ] 前置架构边界、Application ports、Capability SPI、MCP ownership、provider
      state ownership 继续通过。
- [ ] 完成并记录全量 `pytest`、`lint-imports --no-cache`、architecture tests、
      Ruff 和 mypy 结果；既有 baseline failure 与本轮回归分开报告。
- [ ] 代码、测试和规范变更按项目约定使用中文提交说明；本 PR 完成后停止纯解耦
      重构，不新增业务功能。

## Out of Scope

- 不新增 Browser/Sandbox/Checkpoint 等真实业务 Capability。
- 不改变 Provider 协议、工具语义、权限策略、Session JSONL 格式、Memory 行为、
  CLI/TUI 交互、Application event contract 或评测指标。
- 不引入第三方 DI、Service Locator、迁移脚本、向后兼容 fallback 或与本轮无关的
  格式化/质量债务清理。

## Open Questions

无。用户已明确本轮范围、兼容性边界、Builder 约束和验收方式；技术未知项通过
当前源代码、既有架构测试和 planning design 解决。
