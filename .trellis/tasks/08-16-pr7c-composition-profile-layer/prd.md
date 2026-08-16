# PR7c Composition Profile Layer

## Goal

在 PR7b 已彻底删除 MCP 的基线上，用不可变的显式 Profile 描述 Minimal、Coding、Full 三种 Agent
产品组合。Profile 选择 Provider、execution backend、permission strategy、tools、capabilities、prompt
layers 与 product facade，但不成为新的 God Object，也不把产品差异重新编码为 feature bool。

## Confirmed Base Boundary

- PR6/PR7a 的 `build_meta_agent()` 接收已构造 Provider 与已绑定 `LionTool`，主动注入 caller-owned
  `ToolRegistry`，以空 CapabilityRegistry 复用唯一 Provider/Session/Context/Usage/Core runtime，返回
  feature-neutral `MetaAgent`；PR7b 删除 MCP 不改变这条 Bare 边界。
- PR7b 目标图不含 MCP 或 ToolEnvironment；Full Product 暂时仍通过 `PRODUCT_CAPABILITIES` 选择
  Skill/SubAgent/Plan/Memory，Profile 必须取代该字符串集合而不是包装它。
- `build_agent_composition()` 是唯一一次性 Composition Root；Profile 必须进入该入口，不能新建第二套
  loop/runtime/session 或 service locator。
- Coding `run_shell` 仍直接绑定 `subprocess.run`；`PermissionPolicy` 仍由 builder 固定创建；base prompt
  与 tool selection 仍藏在 `AgentConfig`；extra Capability 仍藏在 `AgentDependencies`。
- Capability prompt/session/resource contributions 已通过 `CapabilityRegistry` 聚合并由同一
  `PromptComposer`/runtime lifecycle 消费，无需修改 Kernel/Harness。

## Requirements

- 提供 frozen/slots、只承载组合数据的 `MinimalProfile`、`CodingProfile`、`FullProfile`；公共 Profile
  不接受任意 capability-name set，也不提供 feature bool。
- `MinimalProfile` 显式携带 Provider/runtime config、外部依赖、调用方 tools、permission strategy、
  neutral prompt 与 Meta facade 选择；内置 Capability 固定为空。
- `CodingProfile` 显式携带 Coding tools、command execution backend、coding permission/safety、coding
  prompt 与 Meta facade 选择，并以可选 `SkillComposition` 值而非 bool 决定是否组合 Skill。
- `FullProfile` 固定组合 Coding 产品形态、Memory、Plan、SubAgent 与默认 Skill，选择完整 `Agent`
  facade；第三方扩展以 immutable `CapabilitySpec` values 组合，不放进 dependencies。
- `AgentConfig` 收敛为 Provider/budget/permission mode/session role/observer 等通用运行值，删除
  `custom_system_prompt`、`custom_tools`；`AgentDependencies` 删除 `extra_capabilities`。
- 增加窄 `CommandExecutionBackend` seam；Coding/Full 的 `run_shell` 绑定 Profile 选择的 backend，默认
  local backend 保持现有 shell 输出/超时语义，测试可注入 fake backend。
- 增加 `ToolPermissionStrategy` Protocol；现有 `PermissionPolicy` 实现该契约，Profile 提供的 strategy
  原样进入 `PermissionMiddleware`，middleware 不认识 Profile 或 Capability。
- `build_agent_composition()` 收敛为单一 Profile 输入；删除公开 `capabilities=` 与
  `PRODUCT_CAPABILITIES`，Feature-specific construction branch 只存在于 Composition Root。
- `build_meta_agent()` 使用 MinimalProfile；新增 CodingProfile 构造入口；Full `Agent` 使用 FullProfile；
  SubAgent/Skill child 使用 CodingProfile，不递归构造 Memory/Plan/SubAgent。
- 不恢复 MCP、Autonomy、Dream、Learning，不建立 Supervisor、Profile registry、DI container 或
  compatibility layer。

## Acceptance Criteria

- [ ] MinimalProfile 实际图的 ToolRegistry 只含调用方 tools、CapabilityRegistry 为空，所有高级字段为
  None/不存在，facade 为 MetaAgent。
- [ ] CodingProfile 实际图包含 backend-bound Coding tools、选定 permission strategy、coding prompt 与
  MetaAgent；默认 Capability 为空，Skill 只在提供 `SkillComposition` 时出现。
- [ ] FullProfile 实际图包含 Memory、Plan、SubAgent、默认 Skill 与 extension specs，Capability prompt
  layers 进入同一 PromptComposer，facade 为完整 Agent。
- [ ] 三种 Profile 与 Full object graph 均不存在 MCP 或 Supervisor 节点。
- [ ] SubAgent child 使用 CodingProfile，不构造 Memory、Plan、SubAgent 或其他 Full-only Capability。
- [ ] Profile dataclass 不含 feature bool、运行时协调方法、registry lookup 或 mutable lifecycle state。
- [ ] Kernel/Harness 没有 Profile/Feature-specific branch 或反向 import。
- [ ] executable object-graph tests 验证三种图的节点存在性、缺失性、backend/strategy identity、prompt
  layers 与 facade type。
- [ ] 定向测试、架构门禁、全量测试和全部质量基线门禁通过；完成报告展示三种真实 object graph。

## Out of Scope

- MCP 或任何替代 external-tool protocol。
- Supervisor、Autonomy、Scheduler、Dream、Learning。
- 恢复 PR1 延期的 Memory turn lifecycle/provider refresh。
- 新业务 Capability、remote sandbox backend、backend registry、plugin discovery 或 DI framework。

## Dependency and Rollback

- 分支：`muyuzhong/pr7c-composition-profile-layer`；基线：`muyuzhong/pr7b-mcp-total-removal`。
- PR7b 未完成全部 MCP 残留扫描与质量门禁前，PR7c 不得 start。
- 回滚 PR7c 恢复 PR7b 的 capability-only Product 选择，不恢复 MCP 或 Supervisor。
