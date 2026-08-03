# Agent Lifecycle 实施计划

1. 新建 `lion_code/agent_lifecycle.py`，定义窄 Host 协议与 `AgentLifecycle`，迁入目标
   Provider/Thinking 配置逻辑。
2. 在 `Agent` 中创建 lifecycle 实例；保留 public API 薄委托和 `_create_provider()` 动态
   factory，调整构造和 Session restore 的内部调用。
3. 更新/补充 configuration、Thinking、patch-anchor 与模块导入边界测试，不改变 CLI/TUI
   调用点。
4. 更新 `MAINTENANCE.md` 与 runtime-boundaries 事实记录，标记 PRD acceptance criteria。

## Validation

- `python -m pytest -q tests/integration/test_agent_core_runtime.py tests/application/test_coding_session.py tests/tooling/test_skill_registry_view.py`
- `python -m compileall -q lion_code tests`
- `ruff check` / `ruff format --check` / scoped mypy for changed files
- `lint-imports --no-cache`、`git diff --check`、Trellis task validation
- `python -m pytest -q`

## Rollback Point

若 Provider patch anchor、atomic replacement 或 Session recorder 行为变化，回退本切片的
implementation commit；此前已归档的 S3/S4 模块不受影响。
