# PlanRuntime 所有权执行计划

## Implementation Checklist

1. 新增 PlanStatus、PlanState、PlanView、PlanToolOutcome 与 PlanRuntime，迁入 path/prompt/approval/transition 事务。
2. 在 Agent composition root 创建 Runtime；删除四个 Plan 字段和 `_generate_plan_file_path()`、`_build_plan_mode_prompt()`、`_execute_plan_mode_tool()`。
3. 把 Agent toggle、approval setter 和内部 enter/exit controller 方法改为薄委托，Permission mutation 只留在 PlanRuntime。
4. 把 ToolContext 改为 `plan: PlanView`，PermissionMiddleware/PermissionPolicy 改为读取实时 `context.plan.file_path`。
5. 删除 `_execute_tool_call()` Plan path 同步，机械更新 ToolContext fixtures。
6. 修改 SessionLifecycle/AgentRuntimeCoordinator host contracts，clear/restore/pending reset 全部调用 PlanRuntime 命令。
7. 让动态基础提示刷新调用 PlanRuntime.refresh_prompt()，避免 active Plan prompt 丢失。
8. 增加 PlanRuntime 单元测试和 Agent/ToolRuntime 集成回归，覆盖所有事务分支与失败不变量。
9. 扩展架构断言和 import-linter 边界，阻止旧字段、双写、Owner 外 mutation 与 Core/Provider 反向依赖。
10. 按 `trellis-update-spec` 七段契约要求更新 runtime-boundaries；完成完整质量矩阵和独立 Trellis check。

## Focused Validation

```powershell
python -m pytest -q tests/test_plan_runtime.py
python -m pytest -q tests/tooling/test_agent_runtime.py tests/tooling/test_permission_middleware.py
python -m pytest -q tests/integration/test_agent_core_runtime.py
python -m pytest -q tests/application/test_coding_session.py tests/tui/test_tui_app.py
python -m pytest -q tests/architecture/test_runtime_boundaries.py
```

## Full Validation

```powershell
python -m pytest -q
python -m compileall -q lion_code tests scripts
lint-imports --no-cache
python ./.trellis/scripts/task.py validate .trellis/tasks/08-09-plan-runtime-ownership
git diff --check -- .trellis/spec/backend/runtime-boundaries.md pyproject.toml lion_code tests
```

Ruff check、Ruff format 与 mypy 按 `.github/workflows/ci.yml` 和 `docs/quality-baseline-2026-08.json` 执行基线比对，禁止新增 fingerprint。

## Review Gates

- `rg "_pre_plan_mode|_plan_file_path|_plan_approval_fn|_pending_core_context_reset|tool_context\.plan_file_path|context\.plan_file_path" lion_code tests` 只能命中架构断言字符串。
- Agent 不再定义 Plan transaction helper；PlanRuntime 是唯一 PlanState writer 和 Permission mode command caller。
- ToolContext 现有 PlanView 对象在 enter/exit/clear 后 identity 不变且读取最新 path。
- keep-planning、approval exception、missing file 和 context-reset failure 均不会产生半退出状态。
- 新增第三方依赖数为 0。

## Risky Files and Rollback Points

- `lion_code/agent.py`：构造顺序与两套 Plan 入口必须同时迁移，不能残留 facade 外事务。
- `lion_code/agent_runtime.py` / `session_lifecycle.py`：pending reset 只有成功后可清除，clear 与 restore 行为不同。
- `lion_code/tooling/context.py` 及 fixtures：文件数可能超过 PR 指南阈值；若超出，PR 描述量化机械 fixture 数，并说明拆分会要求兼容字段或双写。
- `tests/integration/test_agent_core_runtime.py`：clear-and-execute 当前直接布置私有字段，必须改为公共 PlanRuntime 命令或 test seam。

最终回滚点是一个中文实现提交；归档与 journal 提交随后单独生成。
