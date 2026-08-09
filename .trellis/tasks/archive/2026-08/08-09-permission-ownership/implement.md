# Permission 所有权执行计划

## Implementation Checklist

1. 新增 PermissionMode、PermissionState、PermissionView、PermissionConfirmationSink 与 PermissionController。
2. 在 Agent composition root 创建 Controller；把 `permission_mode` 改成只读 facade，删除 `_confirmed_paths`。
3. 把 ToolContext 改为 `permission: PermissionView`，删除 `permission_mode` / `confirmed_paths`。
4. 修改 PermissionMiddleware/PermissionPolicy：live View 读取、窄 confirmation command 写入、PermissionMode 类型收紧。
5. 删除 `_execute_tool_call()` 和所有 Plan/clear 路径中的 ToolContext permission 同步；Plan mode mutation 全部改为 Controller command。
6. 更新 Runtime/Memory/SubagentFactory/Application/TUI host/read contracts，不暴露 mutable state。
7. 机械更新 ToolContext fixtures 和直接赋值测试，使用 Controller command 或构造目标 mode。
8. 增加 focused tests：live mode、confirmation cache/non-cache、Plan transition、child inheritance、dontAsk 与 architecture single-writer assertions。
9. 按 `trellis-update-spec` 七段契约要求更新 runtime-boundaries，并同步 import-linter 禁止上层 Permission 模块进入 Core/Provider。
10. 运行完整质量矩阵；由独立 Trellis check 子代理复核并直接修复发现。

## Focused Validation

```powershell
python -m pytest -q tests/tooling/test_permission_policy.py tests/tooling/test_permission_middleware.py
python -m pytest -q tests/tooling/test_skill_registry_view.py tests/tooling/test_agent_runtime.py
python -m pytest -q tests/integration/test_agent_core_runtime.py
python -m pytest -q tests/application/test_coding_session.py tests/tui/test_tui_app.py
python -m pytest -q tests/architecture/test_runtime_boundaries.py
```

## Full Validation

```powershell
python -m pytest -q
python -m compileall -q lion_code tests
lint-imports --no-cache
python ./.trellis/scripts/task.py validate .trellis/tasks/08-09-permission-ownership
git diff --check -- .trellis/spec/backend/runtime-boundaries.md pyproject.toml lion_code tests
```

Ruff check、Ruff format 与 mypy 按 `.github/workflows/ci.yml` 和 `docs/quality-baseline-2026-08.json` 执行基线比对，禁止新增 fingerprint。

## Review Gates

- `rg "_confirmed_paths|tool_context\.permission_mode|context\.permission_mode|context\.confirmed_paths" lion_code tests` 只能命中架构断言字符串。
- ToolContext dataclass 不再声明旧字段。
- PermissionMiddleware 无 `set_mode` 能力；mode mutation 只出现在 PermissionController。
- Agent direct `permission_mode = ...` 和 PermissionState Controller 外 write 均被架构测试拒绝。
- Plan behavior tests证明当前 transaction 行为不变，且无需 ToolContext sync。
- 新增第三方依赖数为 0。

## Risky Files and Rollback Points

- `lion_code/agent.py`：Plan 有两套入口和 clear path，最容易遗漏 direct assignment/sync。
- `lion_code/tooling/middleware.py`：confirmation cache 在 default/auto 下行为不同，必须保留。
- `lion_code/session_lifecycle.py` / `session_memory_coordinator.py`：只读 host 类型迁移不能扩大职责。
- ToolContext fixture 文件数可能超过 PR 指南阈值；若超出，PR 描述必须量化机械 fixture 数，并说明拆分会要求兼容字段/双写。

最终回滚点是一个中文实现提交；归档与 journal 提交随后单独生成。
