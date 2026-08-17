# PR9 Legacy Memory / Dream / Learning Total Removal

## Goal

在最新 `master`（`26d0dd4`，PR8 Capability Plane）上删除旧 Memory、Dream、Learning 的完整生产链路，得到一个不创建、不暴露、也不通过兼容层保留这些对象的干净基线。未来 Memory 重新设计不属于本 PR。

## Confirmed baseline facts

- `FullProfile` 当前在 `composition/agent_builder.py` 中选择 `skill`、`subagent`、`plan`、`memory`，并由 `_build_session_graph()` 创建 `SessionMemoryCoordinator`、`ProviderTextQueryService` 和 `MemoryCapability`。
- `AgentComposition`、`AgentDependencies`、`Agent` facade、Application ports/commands 和 REPL/TUI 都有旧 Session Memory 状态或命令委托。
- `lion_code/tools.py` 的写文件路径还调用 `rebuild_memory_index_if_needed()`；它是旧 Auto Memory 的生产适配钩子。
- `ProjectionLayer` 在生产中只有 `capabilities/memory.py` 的真实实现；Plan 使用的是 `PromptLayer`，没有第二个非 Memory 生产使用者。
- `ProviderTextQueryService` / `TextQueryService` 只被旧 Memory runtime 使用；`domain_ports.ModelQuery` 与 `model_query.ProviderModelQuery` 仍被 Autonomy runtime 使用，属于保留的 generic ModelQuery seam。
- canonical Session/history 仍由 `core/session/`、`session_runtime/SessionRepository`、`SessionRecorder`、`ContextManager` 和 `ContextCompactor` 负责，不能随旧 Memory 一起删除。
- `lion_code/core/session/memory.py` 是 JSONL session replay 的 compaction entry 模块，不是项目级 Session Memory，必须保留。

## Requirements

### R1. Legacy Memory total removal

删除旧 Memory 生产模块、对象和适配器：`memory.py`、`memory_runtime/`、`session_memory.py`、`session_memory_coordinator.py`、`capabilities/memory.py`，以及所有仅服务这些模块的类型、notice/adapter/port、Provider text query、配置/依赖、测试和生产引用。不得加入 `NullMemory`、`DeprecatedMemory`、`LegacyMemory` 或 fallback。

### R2. Dream total removal

删除 `dream.py`、`dream_adapter.py`、`DreamCoordinator`、`DreamAgentFactory` 及其专属协议、适配器、测试、active spec/product documentation 和构造引用。历史 Trellis archive 不在本 PR 清理范围内。

### R3. Learning total removal

删除 `learning_runtime.py`、`LearningRuntime`、旧 `/learn` 测试/文档/适配器和仅供该机制使用的 seam。Skill discovery、Skill runtime、Skill capability 和 Skill tool 保留。

### R4. Composition/Profile 收口

将 `FullProfile` 固定为 `Coding + Plan + SubAgent + Skill + extension_specs`；删除 `_CAP_MEMORY`、旧 `_SessionGraph` memory 字段、Session Memory 依赖/组合状态、Memory-specific imports/branches。Minimal/Coding/Full 图都不得创建任何 Memory replacement object。

### R5. Agent/Application facade 收口

删除 `Agent` 中全部旧 Memory 属性、setter、private delegation 和 repository 参数；删除 `SessionMemoryPort`、对应 Application command result/handler/dispatch，以及 `/task`、`/session-memory`、`/handoff`、`/memory` 的旧产品入口/帮助文本。不得保留 deprecated alias。

### R6. ProjectionLayer slot removal

删除 `ProjectionLayer` protocol、`CapabilitySpec.projection_layers`、Registry aggregation、`CapabilityLifecycle.project_context`、`CapabilityRuntime.project_context` 和 `AgentRuntimeCoordinator` 对该 slot 的调用。Generic context preparation/compaction 仍由 `ContextManager`/`ContextCompactor` 负责。

### R7. Session and retained capabilities

保留 canonical session/history、SessionRepository、SessionRecorder、ContextManager、ContextCompactor、Agent Event Stream、generic Capability SPI、Skill、Plan、SubAgent、Autonomy runtime，以及仍有非旧 Memory/Dream/Learning 使用者的 generic `ModelQuery`。CapabilityRegistry 空扩展图必须仍可运行。

### R8. Negative architecture gates

新增或收紧架构测试，至少禁止生产代码中的 `SessionMemoryCoordinator`、`SessionMemoryRepository`、`MemoryCapability`、`DreamCoordinator`、`LearningRuntime`、`_CAP_MEMORY`，并在对应模块彻底删除后验证旧模块文件/目录不存在。门禁不得把 generic `memory` 单词列为全局禁词；应显式保留 `core/session/memory.py`。

### R9. Documentation and package metadata

同步 active product/architecture specs、ownership/test inventory、CLI help 和 package metadata，使文档只描述删除后的四层基线；删除文件不再出现在 setuptools/import-linter/质量基线的 active configuration 中。不得开始设计新的 Memory，也不得继续实现 Supervisor。

## Acceptance Criteria

- [ ] `MinimalProfile` 正常构造，CapabilityRegistry 空扩展成立。
- [ ] `CodingProfile` 正常构造，Skill 只按现有 SkillComposition 出现。
- [ ] `FullProfile` 正常构造，capability graph 只包含 Coding/Plan/SubAgent/Skill/extension specs，不创建 Memory。
- [ ] `Agent` facade 不暴露旧 Memory API，也不接受旧 Session Memory repository 参数。
- [ ] canonical Session save/restore/compaction、JSONL replay 和 Event Stream 回归通过。
- [ ] CapabilityRegistry zero-extension、generic lifecycle、Skill、Plan、SubAgent 回归通过。
- [ ] 生产对象图和模块中不存在旧 Memory、Dream、Learning 实现、Null/Deprecated/Legacy adapter。
- [ ] `ProjectionLayer` extension slot 在无第二个真实生产使用者的证据下完整删除。
- [ ] 新负向架构门禁通过，且不会误杀 `core/session/memory.py` 或未来 generic `memory` 命名。
- [ ] `py_compile`/`compileall`、定向测试、全量测试、import-linter、`git diff --check` 和适用质量基线检查完成；结果区分本 PR 范围与既有 dirty-worktree baseline。

## Out of scope

- 重新设计、迁移或替换 Memory。
- 继续实现 Supervisor、Autonomy re-home、Dream re-home 或 Learning replacement。
- 删除 canonical Session/history、JSONL legacy read-only migration、compaction entry、ContextManager/Compactor、Event Stream、Skill、Plan、SubAgent 或 generic ModelQuery。
- 清理历史 Trellis archive、历史 rollout、benchmark corpus 快照或仅用于历史记录的维护台账条目，除非它们被当前架构测试或 active product contract 直接读取。

## Open questions

无。用户已明确 total removal、无兼容层、ProjectionLayer 按真实生产使用者判定、保留 Session/Skill/Plan/SubAgent/generic seams，并禁止开始新 Memory/Supervisor 设计。
