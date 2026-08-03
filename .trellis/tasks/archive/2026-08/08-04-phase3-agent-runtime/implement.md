# Agent Runtime Coordinator 实施计划

1. 在 `lion_code/agent_runtime.py` 定义 `AgentRuntimeHost` 和
   `AgentRuntimeCoordinator`，先迁入 Core 构造、observer/session-ready、usage/output
   capture、background-operation 与 context projection/compaction。
2. 将 `Agent` 的 Core-scoped state 改为 coordinator 所有，并提供前序模块和测试所需的
   兼容属性；保留 Agent 的 provider/renderer 动态 factory。
3. 迁移 `chat()`、`run_once()`、`run()`、clear/restore/compact/abort/close 等编排方法，
   仅留下 MCP 发现、Memory/Plan/Autonomy/Tool host 回调和薄公开入口。
4. 补充 coordinator 的无反向导入、单历史、renderer patch、timeout/close/restore
   契约测试；更新既有测试中的内部替身时保留 public behavior。
5. 更新 `MAINTENANCE.md`、runtime boundary、父任务验收与本 PRD，记录可复现的物理
   `agent.py` 行数和验证结果。

## Validation

- `python -m pytest -q tests/runtime/test_agent_runtime.py tests/test_agent_run.py tests/integration/test_agent_core_runtime.py tests/application/test_coding_session.py tests/memory_runtime/test_core_integration.py tests/tooling/test_mcp_adapter.py`
- `python -m compileall -q lion_code tests`
- changed-scope `ruff check`、`ruff format --check` 与 mypy
- `lint-imports --no-cache`、`git diff --check`、Trellis task validation
- `python -m pytest -q`

## Risks and Rollback

高风险点是 observer 订阅顺序、Core/JSONL message identity、Memory overlay 时序、
timeout cancellation 和 close 的 finally 链。若任一 invariant 回归，回退 S6 implementation
commit；S3-S5 已归档模块和此前 Provider 生命周期行为不受影响。
