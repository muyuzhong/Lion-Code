# PR8 Capability Plane rebuild

## Goal

把 Bare Agent Extraction（PR1/PR6）删除出去的 Agent-level Feature 重新放回 Capability Plane。
原则：Capability 表达"这个 Agent 可以额外做/感知/记住什么"，不是"Agent 如何运行"。
Kernel/Harness 保持 feature-blind，Feature 行为只经窄 SPI 接入。

主工程量是 **Memory re-home**：PR1 从 Core 生命周期删除的 turn 驱动 Memory 自动行为
（`<relevant-memory>` 召回、overlay 注入、turn 后自动抽取）以 Capability 身份恢复，
7 个 `_REHOME` skip 测试解除。其余 Capability（Skill/Plan/SubAgent）做 slot 复核；
MCP 已在 PR7b 彻底删除，不复活。

## Confirmed Base Boundary

- 窄 SPI 已存在且稳定：`ToolSource` / `PromptLayer` / `TurnParticipant` / `SessionParticipant` /
  `AsyncCloseable` / `CapabilitySpec.requires`（`lion_code/capabilities/types.py`），
  `CapabilityRegistry` 聚合、`CapabilityRuntime` 分发 lifecycle。
- 已有 concrete capability：Skill（ToolSource）、SubAgent（ToolSource）、
  Plan（ToolSource + PromptLayer + SessionParticipant）。
- PR7c Profile：`MinimalProfile`（零 capability）/ `CodingProfile`（Coding 工具 + 可选 Skill）/
  `FullProfile`（+ Memory/Plan/SubAgent + 扩展 specs + 完整 Agent facade）。
  Feature 构造 branch 只在 Composition Root 的 `_normalize_profile` 与 `_build_*` helper。
- PR1 删除的 Memory 桥接点（本 PR 恢复目标）：
  `chat()` 的 turn snapshot/update 编排、`prepare_core_context` 的 overlay 注入、
  `abort()` 的 prefetch 取消、`SessionLifecycle` clear/restore 的 memory reset、close 的 memory close。
  `SessionMemoryCoordinator` 类与全部状态/命令面保留，当前只服务独立命令，不进 turn 循环。
- `agent_runtime.py` / `session_lifecycle.py` 在 `tests/architecture/test_bare_composition.py`
  的 `_BARE_GENERIC_FILES` 扫描清单内：禁止 import feature 模块、禁止引用
  `SessionMemoryCoordinator` / `MemoryCoordinator` 等 `_FEATURE_SYMBOLS`。
  恢复 Memory 只能通过 generic 端口，不允许符号级特判。
- Memory side query：`ProviderTextQueryService(provider, model)` 固定持有初始 provider 对象；
  PR2/PR6 删除 ProviderManager→Memory 通知后，provider 热替换后 query service 不刷新
  （spec 记录为"留给下一阶段 Feature Re-home"）。
- MCP：PR7b 已全链路删除（client、Capability、adapter、ToolEnvironment），`McpManager` 不存在。
- SubAgent child 已走 `SubagentFactory → build_coding_agent → CodingProfile →
  build_agent_composition`（同一 Kernel/Harness runtime），未见第二套 Agent runtime。

## Requirements

### R1 Memory Capability（主工作）

- Memory 以 `CapabilitySpec(name="memory")` 注册进 Full 图的 `CapabilityRegistry`，
  经下列 slot 接入，不新增 Memory 专属 Kernel/Harness 钩子：
  - **TurnParticipant**：turn 开始固定三层 overlay 快照并启动非阻塞召回预取；
    turn 结束合并工具事实 + 受限语义 patch 保存 Session Memory，刷新下一轮 overlay。
  - **SessionParticipant**：new/restore session 时清空 auto overlay、重载 project/session memory、
    重置注入报告。
  - **ProjectionLayer（新 slot，见 R2）**：把 `<relevant-memory>` 注入当次 Provider 投影的
    最后一条用户消息，不进入 canonical history / JSONL / 系统提示。
  - **resources（AsyncCloseable）**：关闭时回收预取任务。
- 模型查询走 narrow dependency：`ProviderTextQueryService` 的 provider 改为可惰性解析
  （对象或 factory），组合根传入 live provider 访问器；ProviderManager 不感知 Memory，
  不恢复任何 sink/通知。
- 子 Agent 语义保持：`is_sub_agent=True` 时不预取、不抽取（现有 coordinator 内部 gating 保留），
  overlay 快照仍构建。
- abort/timeout 后：after-turn 仍保存确定性工具事实，未消费的预取结果不得在后续轮错误浮现。

### R2 SPI 最小扩展（仅在现有 slot 证明不够处）

- 新增 **`ProjectionLayer`** protocol：对每次模型调用的 Provider 投影做非破坏性叠加，
  签名携带 token 预算；`CapabilitySpec` 增加 `projection_layers` 元组字段，
  registry 聚合、`CapabilityRuntime` 按依赖序折叠分发。
  该 primitive 与 Memory 无关（任何"临时上下文贡献"型 Feature 均可使用），
  不引入 CapabilityContext/ServiceLocator/Agent 引用。
- `TurnParticipant.before_turn` 签名增加本 turn 的 `user_message: str`；
  调用点从 `chat()` 头部移到压缩检查之后、`prompt()` 之前（快照/索引边界与 PR1 前语义一致）。
  `after_turn()` 位置与签名不变。现有 capability 无 TurnParticipant 实现，仅测试 fake 需同步。
- `CapabilityLifecycle` 端口增加 `project_context`：`AgentRuntimeCoordinator.prepare_core_context`
  在 ContextManager 投影后经该端口分发，自身不认识任何 Feature。

### R3 其余 Capability slot 复核（复核为主，改动最小）

- **Skill**：维持 ToolSource 单 slot；Skill 说明由工具描述与动态上下文承载，不新增 PromptLayer。
- **Plan**：维持 ToolSource + PromptLayer + SessionParticipant；Plan state 自持；
  Kernel 不知道 Plan（PR3 已保证）。clear-and-execute 不恢复——Bare Kernel 无真实需求，
  不为单一 Feature 发明 context-transition primitive。
- **SubAgent**：维持 ToolSource 单 slot；确认 child 经 `SubagentFactory → build_coding_agent →
  CodingProfile` 复用同一 Kernel/factory，无第二套 runtime；补架构断言（如缺失）。
- **MCP**：保持删除。在 spec 记录未来外部工具 Capability 的生命周期契约：
  连接资源必须由 capability 自持经 resources/AsyncCloseable 关闭，
  generic ToolEnvironment 不得因协议客户端存在。

### R4 门禁与文档同步

- `_FEATURE_MODULE_PREFIXES` 增加 `lion_code.capabilities.memory`，
  bare 通用路径扫描覆盖新模块；Bare 图（Minimal/MetaAgent）零 capability 行为不变。
- spec 更新：`capability-spi.md`（ProjectionLayer/before_turn 签名/memory 贡献）、
  `four-layer-ownership.md`（PR8 状态：PR1 迁移期问题闭环）、`runtime-boundaries.md`（memory 接线）。

## Acceptance Criteria

- [ ] 关闭所有 Capability 时（MinimalProfile/MetaAgent）行为与 PR7c 完全一致：现有 bare 测试
  全绿，无新增 feature 符号进入 bare 通用路径。
- [ ] 每个 Capability 独立可组合：registry 单独注册任一 spec 均合法；Memory spec 卸载（不组合）
  时 Full facade 其余功能不受影响；close 按逆依赖序释放资源。
- [ ] Capability 只经窄 SPI 接入：无 Agent/AgentHarness 引用、无 CapabilityContext/
  ServiceLocator/巨型 AgentCapability 接口（架构测试持续强制）。
- [ ] Kernel 不 import 任何具体 Capability：`core/`、`context/` 无 capabilities/feature import。
- [ ] Harness 无 Memory/Plan/SubAgent/MCP 特判：`agent_runtime.py`、`session_lifecycle.py`、
  `tooling/` generic 文件经 `_BARE_GENERIC_FILES` AST 扫描零违规。
- [ ] MCP 资源生命周期不污染 generic ToolEnvironment：ToolEnvironment 已不存在且不复活。
- [ ] SubAgent 基于同一 Agent kernel/factory：child 经 CodingProfile 进入唯一 composition root，
  架构断言存在且通过。
- [ ] PR1 删除的 7 个 `_REHOME` skip 测试全部解除并通过（overlay 只进 Provider 投影、
  不进 canonical/JSONL；快照跨轮固定；clear/restore 清空 overlay；corrupt memory 不被覆盖；
  turn 后证据+语义合并；语义失败仍存证据）。
- [ ] provider 热替换后 Memory side query 使用新 provider（lazy accessor 测试）。
- [ ] 完成报告逐个列出每个 Capability 使用的 slot 及理由（Skill/SubAgent/Plan/Memory/MCP）。

## Out of Scope

- 恢复 MCP 或任何外部工具协议。
- Supervisor（Autonomy/Dream/Learning）re-home。
- Plan 的 clear-and-execute / context-transition 恢复。
- Capability 运行时动态装卸框架（卸载=组合期不选择，不做 hot unload）。
- Memory 新增工具（/session-memory 命令面不变）。

## Dependency and Rollback

- 分支：`muyuzhong/pr8-capability-plane-rebuild`；基线：`muyuzhong/pr7c-composition-profile-layer`
  （PR7b #36、PR7c #37 未合并前链式基于 PR7c；上游合并后按 AGENTS.md rebase 到新 master 再 force-push）。
- PR7c 未通过全部门禁前，PR8 不得 start。
- 回滚 PR8 即回到 PR7c 状态：Memory 退回"仅命令面、不进 turn 循环"，
  SPI 恢复三 slot + TurnParticipant 无参签名；不回滚 PR7b/c 的任何删除。
