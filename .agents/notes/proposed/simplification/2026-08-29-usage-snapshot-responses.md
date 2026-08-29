# Agent Note: 删除 UsageSnapshot.responses 无消费者累计字段

- Status: proposed
- 日期: 2026-08-29
- 范围: `lion_code/usage.py`、`tests/test_usage.py`、`tests/integration/`、`tests/architecture/test_runtime_boundaries.py`、`.trellis/spec/backend/usage-ownership.md`

## Problem

`UsageSnapshot.responses`（`usage.py:22`）与 `UsageLedger._responses`（槽 :75/:85，累计 :101，快照映射 :144）没有任何生产消费者：

1. 生产读取者：无——`server/app.py:187-198` 用量端点只投影 input/output；`runtime/agent.py:435-446` 的 `AgentRunResult` 只取 turns/input/output/cache_read/cost；TUI 只读 `token_usage()` 的 input/output。
2. 测试消费者：`tests/test_usage.py:44,67,89`、`tests/integration/test_application_coding_session.py:191,210`、`test_agent_core_runtime.py:491,932`、`test_meta_agent.py:130`、`tests/tooling/test_skill_registry_view.py:93,273`；架构断言 `tests/architecture/test_runtime_boundaries.py:81`（`_responses` 在 `_USAGE_LEDGER_FIELDS`）。
3. 文档：`usage-ownership.md:37,87,93,178,190` 明文把 responses 写进 Snapshot 形状与验证矩阵。

## Proposal

删除 `responses` 字段、`_responses` 槽与累计点（`usage.py` 五处）；同步改 9 处测试断言；`test_runtime_boundaries.py:81` 移除 `_responses`；`usage-ownership.md` 的 Snapshot 形状与 §3/§6/§7 描述去掉 responses。

## Why not keep it

与已落地笔记 `usage-snapshot-unused-fields`（PR #53，删除同 spec 的 `reported_cost_usd`/`reasoning_tokens`）完全同族的新残留：responses 是「响应次数」语义，spec 曾把它列为快照契约，但今天没有任何显示面（TUI/desktop/server）消费它。按同一论证删除。

## Acceptance criteria

- `rg -n "\.responses\b|_responses" lion_code/` 仅剩 `UsageSnapshot` 删除后零命中；`usage-ownership.md` 无 responses 描述。
- `tests/test_usage.py`、`tests/integration/` 全绿。

## Risks

- 若未来要展示「已对话 N 轮响应」，可从 Ledger 计数加回——恢复成本 5 行 + spec 一行。