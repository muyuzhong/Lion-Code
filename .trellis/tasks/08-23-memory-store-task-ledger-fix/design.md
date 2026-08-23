# Memory Store 与工具修正设计

## Boundary

保留现有 `lion_code/capabilities/memory/` 作为唯一 owner，直接替换错误的一期实现，不增加 Repository/Protocol、缓存、后台任务或兼容层。

## Persistence

- `semantic_entries` 按最终设计保存 scope/kind/stable key/content/trigger/pinned/单个 typed evidence/paths/timestamps/archived_at。
- `tasks` 保存 project/stable key/title/objective/summary/next action/status/refs/timestamps/archived_at。
- 两表都用 `archived_at IS NULL` 的部分唯一索引约束 active stable key。
- schema 版本只接受当前版本。初始化在首次连接的 `BEGIN IMMEDIATE` 临界区内完成，其他实例等待后复核，避免 fresh DB 竞争。
- store 不保留长生命周期缓存；动态 review 只在读取时计算。

## Operations

- 相同 active semantic key 原位更新；若 pinned 则拒绝。restore 与 active key 冲突时拒绝。
- task create/update 复用一个 `remember_task`；complete/reopen/archive/restore 由 `manage_memory` 表达。
- `recall_memory` 只做规范化 stable-key exact 与 literal contains，固定 top-k，不建立索引系统。
- `review_memory(view=needs_review|archived|pinned_overflow)` 返回有界 id 与原因；本 child 只计算 overflow，实际 pinned 注入由后续 child 消费同一选择逻辑。
- `set_memory_pinned` 与 `purge_memory` 是唯一确认型 mutation。

## Failure Contract

输入错误返回现有结构化 tool error；数据库版本、损坏、约束或打开失败显式暴露路径与原因，不转成空结果。任何写入都在单事务内完成。

## Rollback

从 FullProfile 移除 Memory 注册即可停止产品暴露；数据库原文件保留。不得自动删除或迁移旧数据库。
