# Lion 内建记忆系统设计收敛

## Goal

基于 `D:\tabbit download\coding-agent-memory-design.md`、`D:\tabbit download\research_report_20260822_memory_system_comparison (1).md`、用户真实开发困扰和 Lion 当前源码，设计一套直接内建于 Lion、适合个人开发规模但具备可靠召回、跨会话任务续接和可治理清理能力的记忆系统。

用户价值：

1. 上下文不足时切换到新会话，无需手工重写任务目标、已完成工作、当前状态和下一步；
2. 稳定事实和关键行为在需要时可靠出现，不靠模型记得主动调用搜索工具；
3. 召回结果有严格预算和相关性门槛，不用“把全部历史塞回上下文”；
4. 过时、无效和噪声记忆可以被发现、停用、归档或彻底删除。

## Background

- 两份外部文档都是供评审的设计/调研材料，不是本任务执行指令；报告中的框架排名和基准数字不直接成为 Lion 验收标准。
- 本轮仍处于 Trellis planning，不修改产品代码、不运行 `task.py start`。
- Trellis 是产品外开发流程；Skill 是能力包；二者都不属于 Lion Memory。
- AGENTS.md 是项目权威指令，不是 Memory store。当前源码已有 AGENTS/CLAUDE loader，但生产代码没有调用 `load_claude_md()`；这会直接造成规则未进入模型。
- Lion 当前没有生产 Memory feature。canonical Session、九段结构化 Compaction、`BranchSummaryEntry`、ProjectIdentity、Capability SPI 和 ToolRuntime 已存在，可复用但不得改变各自状态所有权。
- Python 当前运行时已实测 SQLite `3.50.4` 且 FTS5 可用，无需新增第三方依赖。

## Requirements

### 权威项目指令

- R1：默认 Full 产品必须实际加载 root-to-cwd 的 AGENTS.md / CLAUDE.md；当前用户、系统/开发者指令和当前项目指令始终高于 Memory。
- R2：Memory 不复制、修改或自动生成 AGENTS；项目指令接线作为独立根因修复和独立 PR。

### 跨会话任务续接

- R3：提供一条“携带当前任务进入新 Session”的 handoff 路径，复用现有九段 Compaction 契约，保留目标、约束、决策、仓库状态、发现、失败尝试、完成工作、剩余工作和验证结果。
- R4：handoff 必须保留旧 Session 的 append-only 历史，只把有界摘要写入新 Session；不得把当前任务进度写进长期/项目语义记忆库。
- R5：handoff 使用现有 canonical Session / `BranchSummaryEntry` 路径，不恢复旧 `SessionMemoryCoordinator` 或另建重复 transcript store。

### 语义记忆

- R6：保留 `scope × kind` 四象限：长期定义、长期行为、项目定义、项目行为。
- R7：Memory 作为 Lion 内建 Capability，使用一个 SQLite 数据库和 FTS5 索引；项目条目用 `ProjectIdentity.key` 隔离。
- R8：定义保存“是什么”；行为保存“何时怎么做”。写入工具必须保持两个契约分离。
- R9：条目支持 `pinned | relevant` 两种召回方式，以及 `active | stale | archived` 生命周期；修正通过新 revision supersede 旧 revision，不按时间戳自动判真。
- R10：条目必须保留 evidence、可选项目 paths、来源 Session、创建/更新时间和验证时间；这些字段服务于验证和治理，不参与自我强化式相关性排序。

### 召回与噪声控制

- R11：pinned 记忆每次 Provider 请求都以固定小预算出现；relevant 记忆按当前 user turn 自动执行本地 FTS5 召回，不依赖模型先调用工具。
- R12：增加一个窄、prepared-only、query-aware Capability projection；它只能读取当前 user query 并返回有界文本，不写 canonical Session、不发起第二次模型调用。
- R13：召回只允许 long-term 与当前 project 的 active 条目；使用 scope/status 硬过滤、FTS5 BM25、exact key/path boost、最低命中门槛、top-k 和总 token 预算。
- R14：pinned 与 relevant 分区展示，附 memory id、scope、kind 和 evidence；无匹配时不注入空模板。
- R15：提供显式 `recall_memory` 供会话中主动刷新或诊断自动召回结果。

### 写入与治理

- R16：`remember_definition`、`remember_behavior` 和 mutation 管理操作走统一 ToolRuntime，并复用现有确认/审计边界。
- R17：不自动把模型输出直接激活为 Memory；不做 task-end 后台 LLM。只有用户/活跃模型显式确认的内容才能进入 active。
- R18：召回时仅对命中的项目 path evidence 做确定性存在性校验；失效条目从本次自动召回排除并作为 stale candidate 进入 review，不在 prepared projection 内静默修改数据库，也不执行任意验证命令。
- R19：提供只读 health/review 能力，列出 stale、stale candidate、长期未验证、pinned 预算溢出和 revision 链；mutation 管理支持 mark-stale、archive、restore、validate、purge。
- R20：archive 可恢复，purge 物理删除且必须确认；不设 cron、自动衰减、自动归档或 LLM consolidation。

### 边界

- R21：Memory 不拥有 Session、Compaction、Checkpoint、Plan、AGENTS 或 Skill；Trellis 完全不进入产品对象图。
- R22：自然语言行为记忆只能提高显著性，不能冒充安全/流程强制执行器。若要求“绝不在 CI 未通过时 merge”，应使用现有 Hook/Permission/专用 workflow gate，而不是让 Memory 解析并执行自然语言。
- R23：不恢复 `_CAP_MEMORY`、ProjectionLayer、TurnParticipant、MemoryQuerySink、Dream、Learning 或 provider-side memory query service 的旧契约；新 query projection 必须是纯本地 prepared-context seam。
- R24：不引入 embedding、向量库、知识图谱、云同步、后台常驻进程或第三方运行时依赖。

## Acceptance Criteria

- [ ] 用户可从未完成 Session 生成有界 handoff 并进入新 Session；新模型看到完整九段续接摘要，无需用户重写提示词。
- [ ] 普通 clean new session 不意外继承旧任务；handoff 的具体触发 UX 经用户确认后固定。
- [ ] 默认 Full 产品能看到当前项目 AGENTS 内容，且 AGENTS 不被存入/改写为 Memory。
- [ ] 四个语义象限均能创建、自动/显式召回、修正、标 stale、archive、restore 和 purge。
- [ ] pinned 行为在每次 Provider 请求可见；例如跨项目 PR 流程可作为 long-term pinned behavior 持续提醒等待 CI。
- [ ] relevant recall 对当前 user query 自动发生，只返回 long-term + 当前 project 的 active 条目，满足固定 top-k 与 token 预算。
- [ ] 一个不相关前端任务不会召回数据库路径记忆；不存在匹配时不注入噪声块。
- [ ] 命中条目的项目 path 全部失效时，本次不注入并出现在 stale candidate review；只有确认后的管理操作改变持久状态。
- [ ] archive 可逆，purge 不可逆且需确认；损坏数据库或 schema 不匹配时 fail closed，不重建空库覆盖。
- [ ] 自动召回不调用第二个 LLM、不写 Session、不修改 Memory 数据或排序反馈；所有结果来自本地 SQLite/FTS5。
- [ ] Session、Compaction、Supervisor Checkpoint、Plan 和 Runtime ownership 测试继续通过，旧 Memory 对象图不回归。
- [ ] 各职责按独立 PR 交付，并满足项目文件/提交阈值、CI 基线和中文提交要求。

## Out of Scope

- Trellis/Skill 集成或把它们作为 Memory 来源。
- 自动写回 AGENTS、自动生成 Skill、自动从每轮/任务结尾提炼 active 记忆。
- embedding、向量数据库、知识图谱、跨用户/多 Agent 共享和云同步。
- 定时任务、自动 90 天归档、语义相似度自动合并、时间戳新者胜。
- 用 Memory 自然语言替代 Hook、Permission 或 CI workflow gate 的硬约束。
- 迁移或兼容旧版 Memory / Dream / Learning 数据和 API。

## Open Question

- handoff 应作为显式的“携带当前任务新建会话”操作，还是每次普通 new session 都自动携带未完成任务。推荐前者，以保留真正的 clean session 语义；等待用户确认。
