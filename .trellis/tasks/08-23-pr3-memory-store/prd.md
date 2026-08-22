# PR3 SQLite Semantic Memory Store 与治理工具

Parent：`08-22-memory-system-design-convergence`（对应其 implement.md 的 PR3 段）

## Goal

实现四象限语义记忆的存储层与显式工具面：SQLite + FTS5、revision 生命周期、治理操作。先通过 `extension_specs` 测试闭环，不默认启用自动召回（自动召回属 PR4）。

## Requirements

### 存储

- R1：在 `lion_code/capabilities/memory/` 实现 `MemoryStore`、严格 schema 初始化、integrity/version fail-closed、事务边界；不建立单实现 Protocol。
- R2：表结构：`memory_entries`（revision 与生命周期）、`memory_fts`（FTS5，索引 stable_key/content/trigger/paths）、`memory_meta`（schema version）；scope/kind/status/recall_mode CHECK 约束；project_key 约束（project 必填、long_term 必须为空）；active stable-key 唯一性。
- R3：DB 路径 `~/.lion-code/memory.sqlite3`；WAL、foreign key、busy timeout；不引入第三方依赖。
- R4：schema 不匹配或 integrity check 失败时 fail closed，不重建空库覆盖。

### 数据模型

- R5：四象限 `scope(long_term|project) × kind(definition|behavior)`；definition 保存“是什么”（trigger 必须为空），behavior 保存“何时怎么做”（trigger 必填），CHECK 约束强制契约分离。
- R6：`recall_mode: pinned | relevant`；`status: active | stale | archived`。
- R7：字段保留 evidence（非空字符串列表）、可选项目 paths（long_term 必须为空）、source_session_id、created/updated/validated_at、supersedes_id、archived_reason。
- R8：修正同一 stable key 时创建新 active revision 并把旧 revision 置为 archived（supersede），不按时间戳自动判真。不保存置信度、embedding、use-count 排序权重。

### 检索

- R9：FTS5 BM25 + exact key/path boost、scope/status 硬过滤、最低 lexical 门槛、稳定 tie-break、top-k 与 token 预算裁剪。

### 工具面（走 ToolRuntime，mutation 需确认）

- R10：`recall_memory(query, paths=(), include_inactive=false)` 只读；`remember_definition(...)`、`remember_behavior(...)` mutation；`review_memory(scope, older_than_days)` 只读（列 stale、stale candidate、长期未验证、pinned overflow、revision 链）；`manage_memory(id, action, reason)` 支持 mark_stale | archive | restore | validate | purge。
- R11：archive 可恢复；purge 物理删除且必须确认。
- R12：命中条目的项目 path 做确定性存在性校验；paths 全部失效 → stale candidate 供 review，不自动改库；不自动执行 command evidence。

### 边界

- R13：不自动把模型输出激活为 Memory；无 task-end LLM、cron、自动衰减、自动归档。
- R14：MemoryStore 只由 Capability 内部持有；不恢复旧 Memory/Dream/Learning 对象图（`tests/architecture/test_legacy_memory_removal.py` 门禁保持）。

## Acceptance Criteria

- [ ] 四象限创建、隔离（project_key 硬隔离）、召回测试通过。
- [ ] schema 约束、corrupt/version mismatch fail-closed、FTS 索引一致性测试通过。
- [ ] revision supersede 链、stale、archive/restore/purge 测试通过。
- [ ] 并发读写与 ToolRuntime metadata（confirmation 标记）测试通过。
- [ ] CI 基线全绿；架构测试不回归。

## Out of Scope

- QueryContextLayer 自动召回与 FullProfile 默认启用（PR4）。
- embedding、向量库、知识图谱、云同步。
- 旧 Memory 数据迁移。

## 回滚点

取消/回退 Capability tools；数据库文件保留为可恢复用户数据。
