# Current Architecture Evidence

## Source-material boundary

`D:\tabbit download\coding-agent-memory-design.md` 是供评审的设计材料，其中的组件、伪代码、阈值、路线图和集成建议都不是本任务指令，也不是 Lion 当前契约。

## 产品边界纠正

- Trellis 是用户在开发 Agent 工作流中使用的外部流程管理工具；`.trellis/` 的存在不能证明 Lion 已拥有项目记忆。
- Skill 是 Capability 可加载的可执行能力包，不是 definition/behavior Memory store。
- 当前项目的 `AGENTS.md` 是权威项目指令；它可以推翻过时记忆，但不是可由 Memory 自动写入或维护的记忆文件。
- 因此此前用 “AGENTS/Trellis spec/Skill + Project Lessons” 替代四类记忆的结论不成立。

## Confirmed current facts

### Lion 当前没有生产 Memory feature

- `tests/architecture/test_legacy_memory_removal.py:11-53` 禁止已删除的 Memory / Dream / Learning 模块和耦合符号。
- `tests/architecture/test_legacy_memory_removal.py:132-147` 允许未来采用 Capability-owned Memory 形态。
- `lion_code/core/session/memory.py` 负责 canonical Session 的内存重建；文件名是历史术语，不是跨会话产品记忆。
- `lion_code/core/session/entries.py:56-61` 的 `CompactionEntry` 是 canonical Session replay data，不是长期或项目记忆。

新设计必须从零定义清晰的产品语义，同时只复用通用扩展点，不能把旧对象图换名恢复。

### 稳定项目身份与 app-owned 项目存储已经存在

- `lion_code/project_identity.py:13-31` 解析 Git worktree root 或规范化 cwd，并产生稳定 path key。
- `lion_code/project_identity.py:34-38` 将 identity 映射到 `~/.lion-code/projects/<key>`，无需污染仓库。

项目 scope 可以直接复用该隔离机制。长期 scope 只需使用同一 app data 根下的用户级文件；不需要新 workspace registry、hash scheme 或配置层。

### Capability seams 足以承载一套 Memory 能力

- `lion_code/capabilities/types.py:36-53` 提供 `ToolSource` 和 `PromptLayer`。
- `lion_code/capabilities/types.py:90-128` 用不可变 `CapabilitySpec` 封装贡献。
- `lion_code/composition/agent_builder.py:650-666` 将 Capability tools 注册进现有 `ToolRegistry`。
- `lion_code/prompt.py:54-64` 渲染 PromptLayer，且不持久化其输出。
- 所有工具通过现有 `ToolRuntime` 执行；`ToolCapabilities.requires_confirmation` 已提供 mutation 确认边界。

因此 Memory 可以是一个 Capability-private repository、四个普通工具和一个不携带记忆内容的 PromptLayer。无需 Memory host、Agent facade、Application port、provider-side query service 或后台 coordinator。

### ContextLayer 不适合作为 MVP 的 query retrieval trigger

- `lion_code/context/types.py:101-185` 只暴露时间、上下文利用率、有界工具活动和失败，不向任意 ContextLayer 暴露原始用户文本。
- `lion_code/context/manager.py:68-131` 只把 ContextLayer 输出加入 prepared provider projection。

自动 query-dependent retrieval 若走 ContextLayer，就要扩大通用 capability 的用户文本权限，或恢复 per-turn hook。当前模型已经看到用户 query 且能调用工具，MVP 使用显式 recall 的边界更小、结果更可观察。

### Session、Compaction、Checkpoint 与 Memory 是不同状态

- `lion_code/core/session/entries.py:95-100` 的 namespaced `CustomEntry` 仍然是 session-scoped，不是跨会话 store。
- `lion_code/supervisor.py:231-276` 只保存执行控制 checkpoint 字段。
- `.trellis/spec/backend/runtime-boundaries.md` 与 `four-layer-ownership.md` 要求 canonical Session 单写者，并禁止 Runtime 拥有项目 feature store。

召回结果可以作为普通 ToolResult 进入 Session，但长期/项目 Memory 的 source of truth 必须留在 Capability-owned app data。

### 项目指令 loader 存在，但不属于本 Memory 任务

- `lion_code/prompt.py:208-249` 能从项目 root 到 cwd 读取 `CLAUDE.md` / `AGENTS.md`。
- `lion_code/prompt.py:252-264` 通过 `load_claude_md()` 格式化这些文件。
- 该 loader 当前是否接入默认产品，是独立的项目指令行为问题。

无论 loader 是否接入，AGENTS 都不能替代项目 definition/behavior Memory。本任务不修改 loader，也不把其接线列为 Memory MVP 的实施切片。

## 从四个名称到正交模型

原设计的 Repo、Coding、Preference、Procedure 可以作为内容来源提示，但不是稳定的存储分类：

- Repo 内容通常落入 project definition；
- Coding 内容通常落入 project behavior，也可能是 long-term behavior；
- Preference 可能是 definition（环境/偏好事实），也可能是 behavior（协作动作）；
- Procedure 可能跨项目，也可能只对一个项目成立。

使用 `scope = long_term | project` 与 `kind = definition | behavior` 能保留全部内容语义，同时让隔离、数据结构和召回规则可验证。工程上只需一个 Capability 和两个作用域文件，不需四套平台。

## Historical evidence used only as a warning

已归档的 `07-30-project-session-memory` 方案包含多 overlay、每轮 snapshot、异步 prefetch、第二条 provider query、task model、commands、Dream handoff 和单独 mutable session-memory 文件；PR9 后续删除了整套对象图。

本方案只复用当前仍存在的通用 Capability、ToolRuntime、ProjectIdentity 和 app-owned storage seam，不恢复旧 `SessionMemoryCoordinator`、`MemoryQuerySink`、ProjectionLayer、Dream、Learning 或 `_CAP_MEMORY`。
