# Implementation Plan

## 1. Canonical store

- [ ] 删除 FTS/revision/supersedes/stale 代码和 schema。
- [ ] 实现 lazy、并发安全的 schema open/validation。
- [ ] 实现 semantic/task 数据类型、输入规范化、事务与唯一约束。
- [ ] 实现 task/semantic remember、recall、review 与 lifecycle 操作。

## 2. Capability tools

- [ ] 将工具面收敛为 `remember_task`、`recall_tasks`、两个 semantic remember、`recall_memory`、`review_memory`、`manage_memory`、`set_memory_pinned`、`purge_memory`。
- [ ] 按 PRD 设置 read-only、mutation 与 confirmation metadata。
- [ ] 增加 MemoryPolicy PromptLayer；不增加动态内容或第二次模型调用。

## 3. Tests and cleanup

- [ ] 重写旧 contract 测试，覆盖 task 0/1/N、typed evidence、dynamic review、archived view、pin bypass、lazy/fresh concurrent DB。
- [ ] 删除只证明 FTS/revision/stale 的测试，不留兼容断言。
- [ ] 运行 `py_compile`、定向 pytest、ruff 与 mypy；复核 diff 不触及 Session/context composition。

## Stop Conditions

- 发现必须修改普通 ContextLayer、FullProfile 或 handoff 时留给下一 child。
- 不打开真实用户数据库，不编写 migration，不实现 deferred auto recall。
