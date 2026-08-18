# Agent Note: 收口 max_turns 双计数机制（Harness 代次计数与 Ledger 工具边界计数）

- Status: proposed
- 日期: 2026-08-18
- 范围: `lion_code/agent_runtime.py`、`lion_code/core/loop.py`、`lion_code/core/harness.py`、`lion_code/usage.py`、`tests/test_agent_run.py`、`tests/test_usage.py`、`tests/integration/test_agent_core_runtime.py`、`.trellis/spec/backend/usage-ownership.md`

## Problem

`--max-turns N` 这一个旋钮同时驱动两套停止机制，而且计数对象不同：

1. **Harness 代次计数**：`agent_runtime.py:337` 把 `budget.max_turns` 传进
   `LionAgentRuntime`（即 `AgentHarnessConfig.max_turns`）；
   `core/loop.py:131` 在 `turn > max_turns` 时停止，`turn` 按 Provider 调用次数计
   ——包括纯文本最终回复与排队 follow-up（`usage-ownership.md` §1 正是这么警告的）。
2. **Ledger 工具边界计数**：`agent_runtime.py:482-485` 在每次工具调用前
   `record_turn()` 并 `budget.check(snapshot)`，`turn` 按 Core 工具调用边界计。

**spec 与实现矛盾**：`usage-ownership.md` §1 明确写 "The Coordinator must not pass
BudgetPolicy.max_turns to the generic Harness loop"，而代码 :337 就是照传的。
两套计数都被测试钉住：代次停止（`tests/test_agent_run.py:175-185` `max_turns=1`
+ 一次工具调用 → stop_reason "max_turns"；`tests/integration/test_agent_core_runtime.py:325-333`）
与 Ledger 停止（`tests/test_usage.py:145` `turn.kind == "max_turns"`，BudgetPolicy
的 `>=` 边界）。

实际影响：工具型会话里 Harness 代次计数先行触顶并停止（第二轮 Provider 调用就
`2 > 1`），而 `/cost` 显示 "Turns: x/N"（`agent.py:511`）用的是 Ledger 计数——
展示的 turn 数与实际停止点不一致；纯文本会话也会在 N 次模型迭代后停（从未做工具
调用），与文档化语义「Core 工具边界为止」（usage-ownership.md §3）不符。

## Proposal（Option A，推荐：按 spec 收口）

1. `agent_runtime.py:337` 不再把 `budget.max_turns` 传给 `LionAgentRuntime`；
   Harness 的 `max_turns` 保留为通用宿主的独立迭代上限（默认 `None`，测试可显式传，
   作为防死循环保险，但不与预算绑定）。
2. `--max-turns` 只经 `BudgetPolicy` 在 Core 工具边界生效（`before_core_tool_calls`）。
3. 测试重指向：`test_agent_run.py:176-185` 与
   `test_agent_core_runtime.py:325-333` 断言改为验证 Ledger 工具边界停止
   （`max_turns=1` + 一次工具调用仍应停，但停止路径变成预算检查，行为语义一致）；
   Harness 自身的 `loop` 代次上限用例保留在 `tests/core/test_harness.py` 里作为
   通用 harness 行为。
4. `usage-ownership.md` 无需改（实现终于符合它）。

若 owner 认定 Harness 代次计数有独立价值（例如防纯文本死循环），则走
Option B：给 Harness 的计数改独立命名（如 `max_iterations`）与独立配置入口，
与 `budget.max_turns` 解耦，并同步修 spec 的措辞——重点是**同一个旋钮不能有
两种计数语义**。

## Why not keep it

现状的直接辩护是「双保险」：一个防失控迭代，一个管用户预算。但两者读同一个值，
只会让使用者（和 `/cost` 显示）无法预测停止点；真正的安全上限不需要与预算同值。
按「一个事实一个表示」原则，预算语义归 Ledger、通用迭代保险归 Harness 自己的
配置，才是两个机制两个旋钮。

## Acceptance criteria

- `--max-turns N` 下，停止 reason 恒为 "max_turns" 且由 `before_core_tool_calls`
  触发；纯文本最终回复不额外计数（`test_usage.py` 语义保持）。
- `rg -n "budget.max_turns" lion_code` 只剩 Ledger 检查路径一处。
- 全量可跑 unittest 通过；`usage-ownership.md` 的验证矩阵逐条对应实现。

## Risks

- 移除代次计数后，若某个 Provider 在无工具情况下无限生成文本，唯一保险是
  Harness 显式传入的上限——需确认 Agent 路径至少保留一个宽松的绝对上限
  （或依赖 cancellation/超时）。这正是 Option A 里「Harness 保留独立 max_turns
  字段」的原因，实现时不得顺手删掉该字段。