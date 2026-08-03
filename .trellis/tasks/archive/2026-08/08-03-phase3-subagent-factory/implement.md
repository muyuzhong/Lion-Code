# 三阶段-3：`subagent_factory` 实施计划

## Preconditions

- 实施分支：`muyuzhong/phase3-subagent-factory`，基于 `master`。
- 本任务继承已完成的 `autonomy_runtime` 与 `session_memory_coordinator` 边界，但不修改它们。
- 工作树中的质量基线文件和 TUI 审计文档删除必须保持未暂存。

## Steps

1. 先为 Agent tool 和 Skill fork 的构造契约补充聚焦测试：共享 Registry/MCP、权限/API 参数、懒导入与资源关闭。
2. 新建 `lion_code/subagent_factory.py`：定义窄 Host Protocol、策略选择和局部导入的 child 构造方法。
3. 在 `Agent` 初始化工厂，并把两条 fork 路径的策略选择和 `Agent(...)` 构造替换为工厂调用；保留状态通知、运行、计费、错误和关闭在原方法中。
4. 删除 `agent.py` 中只服务于已迁移构造职责的 imports，检查不存在模块顶层反向导入。
5. 更新本子任务的检查记录和维护台账，记录 `agent.py` 行数与相对静态基线。
6. 运行验证、更新任务规范、以中文提交，并在本切片完成后归档；随后再创建 S4。

## Verification

```powershell
python -m pytest -q tests/tooling/test_skill_registry_view.py tests/tooling/test_tool_selection.py
python -m pytest -q
python -m compileall -q lion_code tests
lint-imports --no-cache
ruff check lion_code tests
ruff format --check lion_code tests
python -m mypy lion_code --ignore-missing-imports
git diff --check
python ./.trellis/scripts/task.py validate 08-03-phase3-subagent-factory
```

静态命令采用质量基线比较；只修复本切片引入的新增问题。

## Rollback

若导入、构造参数或 fork 行为出现回归，恢复 `Agent` 内两条原始构造分支并删除新模块；不会涉及持久化数据或外部服务迁移。
