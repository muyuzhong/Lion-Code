# SessionMemoryCoordinator 实施计划

## 执行前检查

- 当前分支：`feat/phase3-session-memory-coordinator`，基于 `master`。
- 父任务：`07-30-project-session-memory`；只继承已实现的 Session Memory
  与三层 Overlay 契约，不扩展任务树、阶段机或 JSONL schema。
- 保留工作区中与本子任务无关的 `docs/tui-migration-audit.md` 删除和
  `08-01-quality-baseline` 任务文件，不使用 `git add -A`。

## 实施步骤

1. 先补最小特征测试，固定 Agent 公共 Session Memory API、Dream 刷新、
   provider/query service 绑定和轮后确定性证据更新的现有行为。
2. 新建 `lion_code/session_memory_coordinator.py`：实现
   `SessionMemoryHost` Protocol、状态所有权、Overlay 生命周期、Session
   Memory 命令、Dream 编排、语义 side-query 和轮后更新。
3. 修改 `lion_code/agent.py`：
   - 在 `ToolContext` 与 Core Runtime 初始化之间构造 Coordinator；
   - Core Provider 就绪后绑定 query service；
   - 将目标方法改为委托，并以兼容属性提供旧私有状态名；
   - 让 clear/restore、abort、provider 切换、close 继续操作同一个内部
     `MemoryCoordinator`。
4. 运行目标测试，确认 `agent.py` 的公共 API、Core Overlay 投影、Dream
   和 Session Memory 生命周期不变；再运行全量测试。
5. 执行 `compileall`、`ruff check`、`ruff format --check`、`mypy`、
   `lint-imports` 和 `git diff --check`，记录与质量基线的差异；必要时只
   修复本子任务引入的错误。
6. 更新 `MAINTENANCE.md` 的三阶段-2 瘦身记录与质量基线测试数，运行
   Trellis 校验，使用中文提交信息提交子任务改动。

## 验证命令

```powershell
python -m pytest -q tests/test_session_memory_coordinator.py tests/test_dream.py tests/test_session_memory.py tests/memory_runtime/test_core_integration.py tests/memory_runtime/test_lifecycle.py tests/integration/test_agent_core_runtime.py
python -m compileall -q lion_code tests
python -m pytest -q
ruff check .
ruff format --check .
python -m mypy lion_code
lint-imports --no-cache
git diff --check
python ./.trellis/scripts/task.py validate 08-01-phase3-session-memory-coordinator
```

## 提交边界

只暂存：`lion_code/session_memory_coordinator.py`、`lion_code/agent.py`、
本子任务测试、必要的 `MAINTENANCE.md`/基线同步和本子任务 Trellis 文档。
不暂存其他活动任务文件或已有删除。
