# Agent Note: 移除 UsageSnapshot 无产品消费者的字段与一次多余转发层

- Status: proposed
- 日期: 2026-08-18
- 范围: `lion_code/usage.py`、`lion_code/agent.py`、`lion_code/application/`、`lion_code/tui/`、`tests/test_usage.py`、`tests/integration/test_agent_core_runtime.py`、`tests/architecture/test_runtime_boundaries.py`、`.trellis/spec/backend/usage-ownership.md`

## Problem

`UsageSnapshot` 的两个累计字段在任何前端/宿主上都没有消费者：

1. **`reported_cost_usd`**（`usage.py:27`）：Ledger 累计 `_reported_cost_usd`
   （:93/:108/:138/:165，每轮加 `usage.cost.total`）。生产消费方：无——
   `agent.py:506-522` 的 `/cost` 用估算公式 `cost_usd`；
   `application/session_stats.py` 只投影 input/output/estimated_cost；
   TUI 只读 `token_usage().input_tokens/output_tokens`（`tui/app.py:1199-1201,1385-1387`、
   `tui/widgets.py:1499-1505`）。引用它的一共只有
   `tests/test_usage.py:48`（断言累计值）与
   `tests/architecture/test_runtime_boundaries.py:79`（私有字段清单）。
2. **`reasoning_tokens`**（`usage.py:21`）：Ledger 累计 `_reasoning_tokens`
   （:107/:153）。生产消费方：无（`providers/openai_compatible.py:1063,1098`
   只做线格式解析，喂给 `Usage` 数据，不读 Snapshot）。只有
   `tests/test_usage.py:44` 断言它。

附带：`Agent.token_usage()`（`agent.py:397-399`）是一行转发壳
（`return self.get_token_usage()`），生产链实际是
`LionCodingSession.token_usage()`（`application/session.py:212`，经
`UsagePort` 协议 `application/ports.py:111`）→ `Agent.token_usage()` →
`Agent.get_token_usage()`（:461）。`usage-ownership.md` §2 写的
"Agent.get_token_usage() to LionCodingSession.token_usage()" 描述的正是这条
多一跳的链；测试直接调 `get_token_usage`（`tests/integration/test_agent_core_runtime.py`
:332/:456/:570/:614/:808/:1028、`tests/tooling/test_skill_registry_view.py:89,225,264`）。

## Proposal

1. 删除 Ledger 的 `_reported_cost_usd`/`_reasoning_tokens` 私有字段、累计逻辑与
   `UsageSnapshot` 的 `reported_cost_usd`/`reasoning_tokens` 字段。
2. 保留且只保留一个宿主入口：保留 `Agent.token_usage()`（协议名），删除
   `Agent.get_token_usage()`，把 9 个测试调用点改名到 `token_usage`。
3. 同步 `usage-ownership.md`：§1/§2 的 snapshot 形状去掉两个字段与对应累计算法描述、
   §3 `record_model_usage` 段去掉 cost/reasoning 累计、§5/§6 去掉对应断言与矩阵行；
   保留 `cost_usd` 估算公式与 provider-reported cost 的线解析（`Usage.cost` 仍存在于
   Core 数据，只是不再进 Snapshot）。
4. 同步测试与架构断言：`tests/test_usage.py:44,48` 删除；
   `tests/architecture/test_runtime_boundaries.py:78-79` 的
   `_reasoning_tokens`/`_reported_cost_usd` 从私有字段清单删除。

## Why not keep it

`reported_cost_usd` 看起来像「供应商报价 vs 估算」对照的前置数据，
`reasoning_tokens` 像「推理计费」的前置数据——但没有任何产品面展现它们，
`usage-ownership.md` 的唯一性/重置/快照契约也不需要它们；它们是 spec 明文
promote 的另一个「未来需求预留」。按 `AGENTS.md` 原则 2 与「不保留向后兼容」，
未消费的 Snapshot 字段只会让冻结值的比较与测试表面变大。`Usage.cost` 尚在线格式
数据里，将来真需要对照时从 Ledger 记录它成本极低。

## Acceptance criteria

- `rg -n "reported_cost_usd|reasoning_tokens" lion_code tests` 零命中（保留
  `providers/openai_compatible.py` 里线解析的局部变量不影响）。
- `rg -n "get_token_usage"` 全仓零命中；`/cost` 与 TUI 用量显示回归通过
  （`tests/integration/test_application_coding_session.py`、`tests/tui/`）。
- 全量可跑 unittest 通过；`usage-ownership.md` 与架构断言同步后
  `tests/architecture/test_runtime_boundaries.py` 绿。

## Risks

- 对外部 embedder 可见的 Snapshot 形状变化（删除两个字段）——当前零消费者，
  且个人项目未发布，风险可接受。
- 若未来要做「供应商报告费用 vs 估算费用」对照展示，需要把 cost 累计重新加回
  Ledger——与今天删除对称。

## 落地

- 提交: `7b23c0288b744b2edee478be68f2f80e5799250e`（squash merge）
- PR: #53（标题：refactor: 移除 UsageSnapshot 无产品消费者的字段与一次多余转发层）
- 门禁证据: 定向测试全绿（排除 5 个已知环境性/既有失败：test_coding_session_ports、test_composition_profiles::test_all_profiles_return_meta_facade、test_capability_migration::test_session_participant、test_agent_core_runtime::test_plan_clear、test_cli::test_repl_routes_generic_command）；CI Quality gates 已通过（2026-08-18）。
