# Agent Note: 删除永久 skip 的僵尸测试（引用已删符号的 plan 集成用例）

- Status: proposed
- 日期: 2026-08-29
- 范围: `tests/integration/test_agent_core_runtime.py`

## Problem

`tests/integration/test_agent_core_runtime.py` 有两个被 `@unittest.skip(_PLAN_REHOME)` 永久禁用的「僵尸测试」，body 引用不存在的符号与非法参数，当前永不执行：

1. `test_plan_clear_and_execute_compacts_without_deleting_history`（:861-933）与 `test_plan_context_reset_failure_keeps_pending_command`（:1013-1059），skip 常量 `_PLAN_REHOME`（:42-45）。
2. 两用例 body 引用 `apply_plan_context_reset`（:1054）与 `pending_context_reset`（:1044,:1057）——在 `lion_code/` 下 rg 零命中（符号已删除）；构造参数 `permission_mode="plan"` 已被 `tests/architecture/test_runtime_boundaries.py:1363` 判非法（`PermissionMode` 无 "plan"）。

## Proposal

删除两个用例与 `_PLAN_REHOME` 常量（:42-45）；其余 plan 相关（非 skip）集成用例保留。

## Why not keep it

这是刻意的 re-home 待办清单：待办应记在 task/issue，而不是永远不跑的测试。按「彻底删除与零兼容包袱」与 tests 门禁现状（1053 passed 全绿基线）删除，不损失任何当前验证能力。

## Acceptance criteria

- `rg -n "_PLAN_REHOME|apply_plan_context_reset|pending_context_reset" tests/` 零命中。
- `tests/integration/test_agent_core_runtime.py` 其余用例全绿（全量可跑 suite 保持 1053 passed 基线）。

## Risks

- 若 plan 语义（clear-and-execute 保留历史、失败保留 pending）未来复用，需按当前 PlanRuntime 契约重写用例——当前符号不存在，无行为可钉。