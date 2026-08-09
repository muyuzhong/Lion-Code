# Usage 所有权执行计划

## Implementation Checklist

1. 新增 UsageSnapshot、UsageLedger、BudgetDecision 与 BudgetPolicy，完整覆盖当前 counters、估算 cost 与 reported cost。
2. 把 UsageObserver 改成无状态 event adapter；删除 UsageTotals ownership 与 sync_usage_from_observer。
3. 在 Agent composition root 创建 Ledger/Policy；删除七个 Agent counters、`_usage_observer` facade、`_get_current_cost_usd()` 和 `_check_budget()`。
4. 修改 AgentRuntimeCoordinator：直接接收 Ledger/Policy，移除 UsageStateHost/cursor/sync，run/run_once/context/turn/reset 全走 snapshot/command。
5. 修改 SessionLifecycle、AutonomyRuntime、AgentLifecycle host 边界，把 effective_window 与 Usage 分离并统一 BudgetPolicy 使用。
6. 把 child Agent、Skill fork 与 Dream 的 direct additions 改为 `record_child_usage()`。
7. 把 Agent/Application/TUI/show_cost 改为 typed UsageSnapshot；删除 dict/counter reads。
8. 更新 SessionMemory host 和所有 tests/fakes/fixtures，去掉旧 usage fields 与 monkeypatch seams。
9. 增加 Ledger/Observer、child aggregation、budget、delta、reset/context tracking 和架构 scanner 回归。
10. 更新 import-linter 与 runtime-boundaries 七段 Usage 契约，跑完整质量矩阵和独立 Trellis check。

## Focused Validation

```powershell
python -m pytest -q tests/runtime/test_usage_observer.py tests/test_usage.py
python -m pytest -q tests/runtime/test_agent_runtime.py tests/integration/test_agent_core_runtime.py tests/test_agent_run.py
python -m pytest -q tests/test_autonomy_goal_loop.py tests/test_dream.py
python -m pytest -q tests/application/test_coding_session.py tests/tui/test_tui_app.py tests/tooling/test_skill_registry_view.py
python -m pytest -q tests/architecture/test_runtime_boundaries.py
```

## Full Validation

```powershell
python -m pytest -q
python -m compileall -q lion_code tests scripts
lint-imports --no-cache
python ./.trellis/scripts/task.py validate .trellis/tasks/08-09-usage-ownership
git diff --check -- .trellis/spec/backend/runtime-boundaries.md pyproject.toml lion_code tests
```

Ruff check、Ruff format 与 mypy 按 `.github/workflows/ci.yml` 和 `docs/quality-baseline-2026-08.json` 执行基线比对，禁止新增 fingerprint。

## Review Gates

- `rg "total_input_tokens|total_output_tokens|total_cache_read_tokens|total_cache_creation_tokens|last_input_token_count|current_turns|last_api_call_time|sync_usage_from_observer|UsageStateHost" lion_code tests` 只能命中架构负向断言。
- UsageObserver source 不包含 totals、last Usage、response cursor 或独立计数更新。
- UsageLedger/Policy 只在 Agent composition root 构造一次；Ledger internal state 只在 `usage.py` 写入。
- `record_child_usage()` 是 child/skill/Dream 的唯一父账本写入口；Context/TUI/Application 只消费 frozen snapshot。
- clear/restore 与 context tracking reset 的范围不同，并由回归测试证明。
- 新增第三方依赖数为 0。

## Risky Files and Rollback Points

- `lion_code/agent_runtime.py`：当前同步 cursor、turn 增量、run delta、context tracking 和 Session reset 全部交织，最容易留下镜像或改变时机。
- `lion_code/agent.py` / `dream.py`：三条 child usage 路径必须迁完，否则 Ledger totals 会漏记。
- `lion_code/autonomy_runtime.py`：max_turns 同时作为 Core tool limit 与 loop tick limit，迁移不能改变既有停止顺序。
- Application/TUI 与测试可能直接假设 dict/counter 形状；不保留兼容字段，必须一次性迁到 snapshot。
- 跨层文件数可能超过 PR 阈值；若超出，量化机械 fixture/consumer 更新，并说明拆分会要求双写或兼容 API。

最终回滚点是一个中文实现提交；归档、journal 与父任务完成记录随后单独生成。
