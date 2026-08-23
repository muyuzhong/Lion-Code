# 验收记忆系统实现

## Goal

对 `master` 上已经合并的 Lion Memory 实现做一次独立、只读的验收审查，判断它是否实现了用户最后确认的产品边界，是否保持 Lion 的状态所有权与安全边界，以及现有测试是否真正证明了这些行为。

最终交付是 findings-first 审查报告，不是第二轮 `trellis-check`，也不是修复提交。

## Review Baseline

按以下优先级解释冲突：

1. 用户最后确认并授权固化的收敛方案：commit `6c9fddd` 中的 `prd.md`、`design.md`、`implement.md`；
2. 当前 `master` 的实际源码、测试和运行时行为；
3. 已归档 parent/child Trellis artifacts，用于判断实现团队声称交付了什么，不用于覆盖更晚的用户决策；
4. 当前 `.trellis/spec/backend/` 架构规范和 CI 门禁。

审查锚点为开始执行时的 `origin/master`。若 master 在审查期间变化，报告必须记录实际 SHA，并只对该 SHA 下结论。

## Requirements

### R1 — 产品范围一致性

- 逐项核对最终设计 R1–R9 与 Acceptance Criteria，形成 `implemented | partial | missing | contradicted | out-of-scope-added` 矩阵。
- 特别核验 Task Ledger、按需任务续接、Semantic Memory 四象限、MemoryPolicy、pinned 注入、动态 review 和离线 lexical 原型。
- 独立识别 Session handoff、AGENTS loader、FTS/relevant 自动召回等是否属于最终一期边界，不能因为代码和测试存在就默认验收通过。

### R2 — 架构与状态所有权

- MemoryStore 必须保持 Capability-private；检查 Agent Runtime、Session、Application、MetaAgent、Supervisor、Plan 与 Provider 是否获得不应拥有的 Memory 状态或 facade。
- 检查 prepared context 是否保持 transient，不写 canonical Session，不触发第二次 Provider 调用，不在召回路径静默写数据库。
- 检查旧 Memory/Dream/Learning 对象图没有以新名称恢复，canonical `core/session/memory.py` 仍只表示 Session reconstruction。

### R3 — 持久化与治理

- 审查 SQLite schema、版本/损坏处理、事务、索引一致性、project 隔离、stable-key 唯一性和 path 规范化。
- 对照最终设计核验 active/archived、动态 needs-review、evidence 类型、pin/unpin/purge 确认边界及 restore 冲突行为。
- 检查任何 revision、stale 持久状态、FTS 或自动召回复杂度是否有被最后产品边界要求；把“设计偏差”和“实现缺陷”分开报告。

### R4 — 召回质量与上下文安全

- 核验 pinned/relevant 的过滤、排序、预算、空结果、中文/短查询、代码块/特殊 token、跨项目串扰和 stale path 行为。
- 检查 query 获取在首轮、tool loop、compaction、restore/new/handoff 后是否使用正确 user query。
- 召回结果不得覆盖当前用户、AGENTS、源码和测试；自然语言 behavior 不得成为隐式工具执行门禁。

### R5 — 工具与权限

- 所有模型可见 Memory 操作必须走 ToolRuntime；核验 read-only/mutation/confirmation metadata 与实际 action 一致。
- 检查普通 remember、manage、restore 是否能绕过 pinned 或 purge 的确认边界。
- 检查工具 schema、错误结果和数据库失败是否会误报为空结果或破坏用户数据。

### R6 — 测试有效性

- 复用已完成 CI/check 结果作为背景，但仍运行与高风险结论直接相关的定向测试。
- 阅读测试是否验证真实数据流和负向行为，避免把 mock、自证实现细节或“删除功能后仍会通过”的 tautological test 当作证据。
- 不重复运行完整 Ruff/mypy/Radon/Vulture/coverage 基线，除非定向审查发现结果依赖它们。

### R7 — Findings 质量

- findings 按 P0–P3 排序，每条包含：用户/系统影响、触发条件、根因、当前源码 file:line、与基线的关系、已有测试为何未覆盖。
- 没有充分源码或可复现证据的内容只能列为 residual risk，不得定为缺陷。
- 设计偏差如果没有负面行为，也要明确标成 scope/contract drift，不冒充 runtime bug。

### R8 — 只读边界

- 不修改产品代码、测试、架构规范、已归档任务或最终设计。
- 只允许创建本验收任务的规划与审查报告；不修复 finding、不重写历史、不创建 PR。
- 保留现有五个未跟踪 Electron/Trellis 任务目录，不读取其内容、不暂存、不提交。

## Acceptance Criteria

- [ ] 报告明确记录审查 SHA、基线层级、检查过的 commits/files/tests 和实际执行命令。
- [ ] 最终设计的每个 Requirement 与 Acceptance Criterion 都有状态和源码/测试证据，而不是只评价已实现功能。
- [ ] PR #89–#93 的四条交付线都被覆盖，并明确哪些属于最终边界、哪些是范围漂移。
- [ ] Memory store、tools、query projection、FullProfile、Session handoff 和项目指令接线的跨层路径均完成追踪。
- [ ] 高风险 persistence/permission/recall 结论至少有一个定向测试或最小复现支持。
- [ ] 每条 P0–P2 finding 都有精确当前文件行号；所有 reviewer 假设均被源码验证或降级为 residual risk。
- [ ] 报告区分“功能缺失”“实现 bug”“架构违规”“过度设计/范围漂移”“测试缺口”。
- [ ] 若没有 finding，报告仍说明已检查范围和剩余风险；若存在 finding，不做任何修复。
- [ ] `git status` 证明产品工作树未被本审查修改，现有无关未跟踪目录保持不变。

## Out of Scope

- 修复、重构、性能优化、schema 迁移、补测试或更新产品 spec。
- 重跑完整 `trellis-check`、全量 CI 或外部 benchmark。
- 评价 Electron/桌面重构任务及其他非 Memory 改动。
- 重新讨论 Memory 产品需求；发现需求冲突时按 Review Baseline 报告，不在审查中替用户改需求。
- 推送分支、创建 PR、合并或发布。
