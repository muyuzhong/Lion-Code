# PR7 Composition Profile Layer

## Goal

在 PR0-PR6 完成 Bare MetaAgent Extraction 后，引入显式的 Composition/Profile 层，
用组合关系表达 Minimal、Coding、Full 三种 Agent 产品形态，而不是把高级能力重新编码为
`AgentConfig` feature bool。

## Background

- 设计必须以最新 `master` 上 `build_meta_agent()` 的真实构造边界为依据，不能预设 Profile 形状。
- 初始研究已拉取并核对 `origin/master@ab3261d`（PR6 merge）；PR7a 后又基于
  `d74f42a` 复核实际 Composition/Product 边界，PR7b/PR7c 均以对应上游提交链为准。
- `build_meta_agent()` 的真实边界是：调用方提供一个已构造 Provider 与一组已绑定 `LionTool`，
  函数创建独立 `ToolRegistry`、neutral `AgentConfig`、外部依赖 seams，并以空 capability 集合
  调用唯一 `build_agent_composition()`，最后只把通用引用交给 `MetaAgent` facade。
- PR7a 已从 Full Product 移除 Supervisor 归属的 Dream、Autonomy、Learning；用户随后决定彻底删除
  MCP 全链路，因此 Profile 只能基于 Skill/SubAgent/Plan/Memory 等保留能力设计，不能把 MCP 包装进
  `FullProfile`。
- 当前 Coding tools 是已绑定函数的 `LionTool`；`run_shell` 直接绑定同步 `subprocess.run`，
  尚无可由 Profile 选择的 execution backend seam。
- 当前 `PermissionPolicy` 在 Composition Root 内直接构造；`permission_mode` 只是通用运行状态，
  尚无 Profile 可选择的 coding permission/safety strategy seam。
- Prompt layer 已有合适的扩展边界：`CapabilityRegistry.prompt_layers` 由 `PromptComposer`
  每次动态读取，无需让 Kernel/Harness 认识具体 Capability。
- Composition Root 可以认识具体 Feature；Kernel 与 Harness 不可以认识 Feature 名称或新增
  feature-specific 分支。
- Profile 选择 Provider、execution backend、permission strategy、tools、capabilities、prompt
  layers 与 product facade，但应保持数据/组合职责，不能成为新的 God Object。

## Requirements

- 提供至少三个显式 Profile 概念：`MinimalProfile`、`CodingProfile`、`FullProfile`。
- `MinimalProfile` 只组合 MetaAgent 基础运行环境，不创建 Memory、Plan、SubAgent 等高级 Capability。
- `CodingProfile` 在 Minimal 基础上组合 Coding Tools、coding permission/safety、execution backend，
  并允许选择性组合 Skill。
- `FullProfile` 在 Coding 基础上组合 Memory、Plan、SubAgent 及其他已有高级 Capability；不得包含 MCP。
- Profile 通过对象组合或明确的组合描述表达产品形态，不增加 memory/plan/mcp/skill/subagent 等
  feature bool 集合。
- Autonomy、Scheduler、Dream、Learning 属于未来 Supervisor，不进入 Profile 内部，也不出现
  `FullProfile(autonomy=True)` 一类接口。
- PR7 直接从现有 `Agent` 产品 object graph 与 facade 移除 Autonomy、Dream、Learning，
  不在 `FullProfile` 外增加临时 Supervisor 组合以保留旧产品行为。
- PR7 在建立 Profile 前彻底删除 MCP client、Capability、tool adapter、ToolEnvironment、配置/facade、
  生命周期、测试与文档链路，不保留禁用开关、空壳或替代协议。
- 独立 Supervisor runtime 实现可作为后续 re-home 的代码保留，但不能由 Profile、Agent facade、
  CLI/TUI/Application 产品路径构造或调用；等待 re-home 的行为测试按项目规则显式 `skip` 并写明恢复条件。
- 不保留过时入口的兼容层或 fallback；若 Profile 替代现有 Composition 选择入口，则直接迁移当前调用方。
- 遵守现有四层所有权、runtime boundary、公共 facade 与测试 seam 的真实约束；具体保持项以源码研究为准。

## Acceptance Criteria

- [ ] `MinimalProfile` 的实际 object graph 不含任何高级 Capability。
- [ ] `CodingProfile` 的实际 object graph 明确包含 Coding Agent 的工具、权限/安全与执行后端形态，Skill 为可选组合。
- [ ] `FullProfile` 的实际 object graph 可以组合现有高级 Capability（至少 Memory、Plan、SubAgent），
  且整个产品图不含 MCP。
- [ ] Kernel/Harness 未因 Profile 增加任何 feature-specific 分支或具体 Feature 依赖。
- [ ] 新 API 不形成 bool explosion，且 Profile 类不承担运行时协调或生命周期 God Object 职责。
- [ ] 自动化测试覆盖三种 Profile 的构造差异与关键边界。
- [ ] 完成后提供三种 Profile 的实际 object graph（由可执行构造/测试或诊断输出验证）。
- [ ] 定向测试、架构门禁和项目要求的全套质量门禁通过；若存在既有基线噪音，单独列明。

## Out of Scope

- Supervisor 层及 Autonomy、Scheduler、Dream、Learning 的重新接线、调度或新实现。
- 新增与三种产品形态无关的 Capability。
- 为旧 Composition/Profile 入口增加兼容层、migration 或 fallback。

## Technical Research Required

- [x] 核对最新 `origin/master` 与当前工作树/PR6 分支的内容关系。
- [x] 通过 CodeGraph 与定向源码读取确认 `build_meta_agent()`、现有 Composition Root、facade、
  execution/permission/tool/capability/prompt ownership 的真实调用链。
- [x] 查明现有 Profile/配置/测试 seam：Provider 与工具可注入；permission strategy 与 shell
  backend 尚不可注入；Capability/Prompt 已有 registry slot；SubAgent 实际只需要窄 child runtime。

## Scope Risk

- Supervisor 产品脱离、MCP 全链路删除与 Profile 引入是三个可独立验收且有先后关系的职责迁移。
  MCP 删除本身涉及大量机械残留清理，但不与 Profile 实现混合；PR7c 继续以 20 文件门槛控制新增设计。

## Task Map

- `08-16-pr7a-supervisor-product-detachment`：先移除 Agent/Composition/CLI/Application/TUI
  对 Autonomy、Dream、Learning 的产品接线，保持独立 Supervisor runtime 代码等待 re-home。
- `08-16-pr7b-mcp-total-removal`：依赖 PR7a，彻底删除 MCP 全链路与仅为 MCP 存在的 ToolEnvironment。
- `08-16-pr7c-composition-profile-layer`：依赖 PR7b，建立 Minimal/Coding/Full Profile，接入 Provider、
  execution backend、permission strategy、tools、capabilities、prompt layers 与 facade。

## Cross-Child Acceptance

- PR7a、PR7b、PR7c 分别满足单一职责、独立测试、独立中文提交与独立回滚点。
- PR7c 的 `FullProfile` object graph 不含 PR7a 已移除的 Supervisor 或 PR7b 已删除的 MCP。
- 三个子任务完成后展示三种 Profile 的真实 object graph，并明确每个图的 Provider、工具、
  backend、permission、capability、prompt layer 与 facade 节点。
