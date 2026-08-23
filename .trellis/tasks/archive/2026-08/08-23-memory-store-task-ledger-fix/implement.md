# Implementation Plan

## 1. Canonical store

- [x] 删除 FTS/revision/supersedes/stale 代码和 schema。
- [x] 实现 lazy、并发安全的 schema open/validation。
- [x] 实现 semantic/task 数据类型、输入规范化、事务与唯一约束。
- [x] 实现 task/semantic remember、recall、review 与 lifecycle 操作。

## 2. Capability tools

- [x] 将工具面收敛为 `remember_task`、`recall_tasks`、两个 semantic remember、`recall_memory`、`review_memory`、`manage_memory`、`set_memory_pinned`、`purge_memory`。
- [x] 按 PRD 设置 read-only、mutation 与 confirmation metadata。
- [x] 增加 MemoryPolicy PromptLayer；不增加动态内容或第二次模型调用。

## 3. Tests and cleanup

- [x] 重写旧 contract 测试，覆盖 task 0/1/N、typed evidence、dynamic review、archived view、pin bypass、lazy/fresh concurrent DB。
- [x] 删除只证明 FTS/revision/stale/auto-recall 的 Memory 测试与模块，不留兼容断言。
- [x] 运行 `py_compile`、定向 pytest、ruff 与 mypy；复核 diff 不触及 Session/Compaction。

## Scope Adjustment

为保证本 child 独立通过测试，Memory 专属 `query_layer.py`、旧 auto-recall 架构测试以及 FullProfile 的 eager/query-aware 断言前置到本 child 删除。通用 QueryContext SPI 与 Session handoff 仍由下一 child 负责；普通 pinned ContextLayer 尚未在本 child 注册。

## Stop Conditions

- 发现必须修改普通 ContextLayer、FullProfile 或 handoff 时留给下一 child。
- 不打开真实用户数据库，不编写 migration，不实现 deferred auto recall。
