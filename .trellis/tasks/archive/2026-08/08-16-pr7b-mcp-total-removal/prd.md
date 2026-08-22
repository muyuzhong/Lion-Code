# PR7b MCP Total Removal

## Goal

在 PR7a 已完成 Supervisor 产品脱离的基线上，彻底删除 Lion 的 MCP 实现与所有相关链路，使产品、
Composition、Capability、Tooling、生命周期、测试、配置和文档都不再认识 MCP。PR7c 的 FullProfile
因此只组合 Coding、Memory、Plan、SubAgent、Skill 与其他显式扩展。

## Confirmed Boundary

- PR7b 基线为 PR7a `d74f42a`；`origin/master@ab3261d` 仍是 PR6。
- 当前 MCP 生产链为：`AgentConfig.mcp_enabled` / `PRODUCT_CAPABILITIES` → Composition Root 创建
  `McpManager`、`McpLifecycleState`、`McpCapability` → 首轮 `before_turn()` 发现并注册远端工具 →
  `ToolEnvironment` 持有并在 SessionLifecycle close 时断开子进程。
- `ToolEnvironment` 除 MCP manager、父子共享与关闭权之外没有其他资源所有权；删除 MCP 后该类型
  整体失去存在理由，不能保留空壳或 Null Manager。
- 当前扫描在 `lion_code`、`tests`、`docs`、`.trellis/spec`、`pyproject.toml`、`.github` 中发现
  47 个相关文件、418 处 MCP 引用；其中 4 个源码文件和 3 个直接测试文件为 MCP 专用。

## Requirements

- 删除 `lion_code/mcp_client.py`、`lion_code/capabilities/mcp.py`、`lion_code/tooling/mcp.py`、
  `lion_code/tooling/environment.py`，以及三个对应直接测试文件。
- 删除 `CAP_MCP`、`McpCapability`、`McpManager`、`McpLifecycleState` 与 `PRODUCT_CAPABILITIES` 中的
  MCP 选择；Composition result、foundation/capability/session graph 不再含任何 MCP 字段或分支。
- 删除 `AgentConfig.mcp_enabled`、`AgentDependencies.tool_environment`、`Agent` 的 MCP facade/state/
  manager/capability 字段，以及公开构造参数和属性；不保留 alias、fallback、deprecated 参数或空实现。
- 删除 `ToolEnvironment` 后，SubAgent 只共享经过选择的 `ToolRegistry`；SessionLifecycle 只关闭
  Core runtime、Provider/background 与 Capability resources，不再存在外部工具环境 finally 分支。
- 删除 MetaAgent、Dream adapter、benchmark worker、CLI/Application/TUI、session/memory 测试与注释中
  为禁用、关闭、过滤或展示 MCP 保留的逻辑。
- 删除 custom-agent/tool-selection 对 `mcp__` 名称的专门测试语义；通用 ToolRegistry 仍允许任意合法
  工具名，但系统不再解释 MCP namespace、读取 `.mcp.json` 或启动 MCP Server。
- 同步架构测试、Capability 测试、import-linter、quality baseline、项目文档、测试 ownership 与 Trellis
  backend specs；非历史任务文件中不得继续把 MCP 描述为当前或可配置能力。
- 保持 Provider、Kernel/Harness、Capability SPI、ToolRegistry、Skill/SubAgent/Plan/Memory 行为不变；
  不在本 PR 建立 Profile、外部工具协议替代品或 Supervisor。

## Acceptance Criteria

- [ ] `lion_code` 中不存在 MCP client、Capability、tool adapter、environment、state、config 或 facade。
- [ ] 构造 Full Product 不读取 MCP 配置、不创建外部 MCP 子进程、不注册 `mcp__*` 工具。
- [ ] `AgentConfig`、`AgentDependencies`、`AgentComposition`、`Agent` 与 SessionLifecycle object graph
  不含 MCP/ToolEnvironment 字段或分支。
- [ ] SubAgent/Skill child graph 不再传递 environment，只共享选定 registry 与通用运行依赖。
- [ ] 在 `lion_code tests docs .trellis/spec pyproject.toml .github` 范围执行 MCP 残留扫描无结果；
  PR7b/父任务等迁移记录允许保留历史说明。
- [ ] 删除的 MCP 专用测试由 strong-negative 架构测试取代：禁止重新出现 MCP 文件、import、配置字段、
  capability name 与 product facade。
- [ ] Kernel/Harness 未新增 Feature-specific branch，现有非 MCP 定向测试与全套质量门禁通过。

## Out of Scope

- Minimal/Coding/Full Profile、command execution backend 与 permission strategy（由 PR7c 完成）。
- MCP 替代协议、远程 sandbox、plugin discovery 或通用 external-tool transport。
- Supervisor、Autonomy、Scheduler、Dream、Learning 的重新接线。

## Dependency and Rollback

- 分支：`muyuzhong/pr7b-mcp-total-removal`；基线：
  `muyuzhong/pr7a-supervisor-product-detachment`。
- PR7c 必须基于 PR7b；不得在 PR7c 恢复任何 MCP 类型或配置。
- PR7b 是单一“完整删除 MCP”回滚点；回滚会恢复 PR7a 上的 MCP 产品链，但不恢复 Supervisor。
- 该 PR 文件数可能超过 20，因为全链路删除必须同步清理源码、直接测试、架构门禁和 spec；改动应以
  删除/机械残留清理为主，不夹带 Profile 实现，并在 PR 描述中记录此单一职责例外。
