# State Ownership 分阶段迁移执行计划

## Ordered Child Tasks

1. 完成并归档 `08-09-session-cancellation-ownership`。
2. 基于最新 `master` 规划、启动并完成 `08-09-permission-ownership`。
3. 基于 PermissionController 的已验证契约规划、启动并完成 `08-09-plan-runtime-ownership`。
4. 基于前三个切片后的 Agent 门面规划、启动并完成 `08-09-usage-ownership`。
5. 对四个子任务执行一次父级集成复核，确认状态箭头、公开 API 和架构契约一致。

## Parent Review Gates

- 每个子任务只有一个职责迁移，出现额外 Owner 时返回规划阶段拆分。
- 每个子任务先跑 focused tests，再跑全量测试、compileall、import-linter、架构测试和 `git diff --check`。
- 每个子任务使用中文提交；只暂存该切片文件，不纳入当前工作区已有的 Trellis 更新。
- 后一子任务不得用兼容层掩盖前一子任务未完成的所有权迁移。

## Final Integration Validation

```powershell
python -m pytest -q
python -m compileall -q lion_code tests
lint-imports --no-cache
python -m pytest -q tests/architecture/test_runtime_boundaries.py
git diff --check
```

## Rollback Points

- 子任务 1：Session + Cancellation 提交。
- 子任务 2：Permission 提交。
- 子任务 3：PlanRuntime 提交。
- 子任务 4：Usage 提交。

父任务不把四个子任务压成一个不可拆分提交。

## Final Integration Result

- 四个子任务已按既定顺序独立完成、中文提交并归档；父任务没有额外产品代码提交。
- 最终全量测试为 629 passed、6 skipped、20 subtests passed；唯一 warning 是既有 Windows GBK spinner 线程编码问题。
- `compileall`、Import Linter 5/5 contracts、Ruff/mypy 基线、架构测试 28 passed 与任务范围 `git diff --check` 均通过。
- 最终 Owner 边界为 SessionIdentityState/SessionLifecycle、ExecutionControl、PermissionController、PlanRuntime、UsageLedger；Agent 只负责组合与只读门面。
- Memory、ToolRegistry、Provider configuration、read freshness 与第三方依赖保持在原范围。
- 全工作树 `git diff --check` 仍只命中用户既有 Trellis 模板改动中的三处空白问题，本迁移未修改或暂存这些文件。
