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
