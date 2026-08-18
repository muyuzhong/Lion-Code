# PR11 Final Architecture Cleanup

## Goal

在本地已完成 PR9 与 PR10 的基线上收尾本轮架构重构：统一 Product Facade，固化
Minimal/Coding/Full Profile 的最终语义，补齐 Capability 增量/可移除验证、公共 API、
目录依赖方向与 Legacy Memory/Dream/Learning 强负向门禁。不得新增功能或设计新的
Memory 系统。

## Confirmed local baseline

- 本任务以本地提交 `e966dc6` 及其 PR10 Trellis 归档为基线，不依赖 GitHub 状态。
- PR9 的生产 Memory/Dream/Learning 模块、旧 facade API 与 ProjectionLayer 已删除；
  `core/session/memory.py` 仅保存 canonical compaction entry，不属于旧 Memory 系统。
- PR10 的 `Supervisor` 位于普通 Agent/Profile/Composition object graph 之外，只拥有
  goal、scheduler、retry/recovery、checkpoint/resume 与 long-running control。
- 基线验证：PR10 focused `87 passed`，架构测试 `88 passed`，import-linter
  `7 kept, 0 broken`，全量 `707 passed, 3 skipped, 10 subtests passed`。

## Architecture review findings

1. `CodingProfile` 仍有可选 `SkillComposition`，与最终 Coding 只含 coding tools/policy
   的定义不一致。
2. `ProductFacadeKind`、Profile `facade` 字段和 `AgentComposition.facade` 保留了
   Meta/Full 双 facade 选择；缺少统一的 `Profile -> MetaAgent` 公共构造入口。
3. `MetaAgent` 私有保存未使用的 `CapabilityRegistry`；Full Product 的通用 API 与
   `MetaAgent` 仍存在重复实现。
4. 现有 Capability 测试证明 empty/full graph，但没有明确证明 Plan、Skill、SubAgent、
   third-party spec 作为独立 `CapabilitySpec` 增量缺席时，通用 runtime 仍可工作。
5. PR9 门禁全局禁止 `MemoryCapability`、`ProjectionLayer` 等通用符号，会与未来从零
   设计的 Memory Capability 冲突；门禁需要只识别旧模块、旧耦合符号和旧组合路径。
6. import-linter 尚未显式固化 Composition 与 MetaAgent 的依赖方向；相关 spec 仍描述
   PR9 的双 facade 和 Coding optional Skill。
7. 当前生产树没有空目录；session persistence/restore/compaction 使用唯一 JSONL 路径，
   本 PR 不迁移或重写该路径。

## Requirements

### R1. One public product facade

- `MetaAgent` 是包级唯一 Agent product facade，只暴露通用执行、对话、事件、会话、
  Provider/Thinking、usage/budget 与 close API。
- 新增单一 `build_profile_agent(profile) -> MetaAgent` 入口；Minimal、Coding、Full 均
  通过同一 Composition Root 后投影为 `MetaAgent`。
- `Agent` 仅作为 CLI/Application 的 CodingSessionBackend 适配器保留，并复用
  `MetaAgent` 的通用 API，不再形成第二套通用 facade 实现；包根不导出 `Agent`。
- facade 不保存 Profile、builder、CapabilityRegistry 或 Feature concrete owner。

### R2. Final Profile definitions

- `MinimalProfile = MetaAgent`：caller tools、neutral prompt、empty CapabilityRegistry。
- `CodingProfile = MetaAgent + Coding Tools + Coding Harness policy`：不含 Skill、Plan、
  SubAgent 或 Memory。
- `FullProfile = CodingProfile + Skill + Plan + SubAgent + extension_specs`。
- 删除 `ProductFacadeKind`、`SkillComposition` 与 facade 字段；不得改成 feature bool、
  capability-name public set、registry lookup 或 lifecycle object。
- `FullProfile.extension_specs` 保留 immutable tuple 语义。

### R3. Capability incrementality (Test C)

- Plan、Skill、SubAgent 与 third-party extension 均以普通 `CapabilitySpec` 注册到同一
  `CapabilityRegistry`。
- 测试分别省略任一 spec，验证 registry aggregation、CapabilityRuntime lifecycle 与
  generic Kernel/Harness path 不依赖具体 capability 名称。
- zero-extension 是合法且可运行的状态；不增加 unregister API、feature toggle 或 Null
  Capability。

### R4. Facade and public API guards

- 用可执行测试固定 `MetaAgent` public surface 和包根 `__all__`。
- 明确禁止 `session_memory`、`active_task`、`handoff` 以及 Memory/Dream/Learning/Plan/
  Skill/SubAgent/Supervisor 专属入口进入 `MetaAgent`。
- Supervisor 继续只通过 structural `AgentFactory`/`AgentPort` 消费 MetaAgent 的公共
  run/event/session contract。

### R5. Legacy architecture negative guards

- 旧 root modules、`memory_runtime/`、session-memory coordinators、Dream/Learning runtime、
  `_CAP_MEMORY` 与旧 provider-query/projection coupling 永久禁止回归。
- 门禁不得使用 `assert "memory" not in repo`，不得禁止 canonical
  `core/session/memory.py`。
- 门禁需用自测证明未来 `capabilities/memory.py` 中一个新的 `MemoryCapability`/
  `CapabilitySpec` 不会仅因名称被拒绝；本 PR 不创建该文件或实现。

### R6. Layer and directory boundaries

- 固化 Kernel/Harness/Capability/Supervisor/Composition/Interfaces 的单向依赖。
- import-linter 与 AST single source of truth 同步增加 Composition、MetaAgent 边界；
  Supervisor、Capability、Kernel 既有边界保持。
- 清理本任务造成或发现的空目录、废弃 ProductFacade 抽象与仅服务 optional Coding
  Skill 的残留；不做无关目录搬迁。

### R7. Runtime invariants

- session JSONL persistence、restore、new session、manual/overflow compaction、usage、
  cancellation 与 resource close 行为不变。
- Supervisor 不进入普通 Profile/MetaAgent/Agent object graph；Agent/Profile 不知道
  autonomy、goal、retry、scheduler 或 long-running state。
- 不新增依赖、功能、Memory/Dream/Learning replacement、migration 或 fallback。

## Acceptance Criteria

- [x] MinimalProfile 构造并运行 MetaAgent，registry 为空。
- [x] CodingProfile 构造并运行 MetaAgent，只含 Coding tools/policy。
- [x] FullProfile 构造并运行 MetaAgent，固定包含 Skill/Plan/SubAgent 与 external specs，
      且无 Memory。
- [x] `MetaAgent` 只有固定的通用 API，旧 Memory/active-task/handoff 与 Feature API 为零。
- [x] Supervisor 在普通 object graph 外，且 factory 可返回任意 Profile 构造的 MetaAgent。
- [x] CapabilityRegistry zero-extension 正常。
- [x] Test C 证明省略任意 Plan/Skill/SubAgent/third-party spec 后通用 runtime 正常。
- [x] session persistence/restore/compaction 的 focused 与全量测试通过。
- [x] Legacy Memory/Dream/Learning 门禁通过，同时 synthetic future Memory Capability 被允许。
- [x] Composition/MetaAgent/Capability/Supervisor/Kernel/Interfaces 架构与 import-linter 全通过。
- [x] 无新增第三方依赖；最终 diff 只含 PR11 与 Trellis task/spec 文件。

## Out of Scope

- 新 Memory System、Memory Capability、Dream、Learning 或语义检索设计。
- 新 Supervisor 行为、远程 scheduler、checkpoint schema 变更。
- session JSONL schema/legacy session reader 迁移、Provider/TUI 功能重写。
- 为未来 Capability 增加 feature flags、dynamic removal API、DI container 或 registry
  service lookup。

## Blocking questions

无。用户已明确要求规划后直接执行、不提问、不启用 subagent，并以本地 PR10 为基线。
