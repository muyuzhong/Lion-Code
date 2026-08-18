# Agent Note: 裁剪通用 Harness 的无宿主面（队列原语、all 排空模式、单工具钩子）

- Status: proposed
- 日期: 2026-08-18
- 范围: `lion_code/core/harness.py`、`lion_code/core/loop.py`、`lion_code/agent_runtime.py`、`tests/integration/test_agent_core_runtime.py`、`tests/core/test_harness.py`

## Problem

`AgentHarness` 对外暴露了一批没有任何宿主（Agent Runtime、应用或测试）使用的面：

1. **队列原语**：`has_queued_messages`（`harness.py:111-112`）、
   `pop_latest_follow_up`（:158-159）、`pop_latest_steering`（:161-162）、
   公共 `append_interrupted_tool_results`（:255-258）、`QueuedMessages.count`
   （:47-49）、`pending_message_count`（:107-109，唯一引用在
   `tests/integration/test_agent_core_runtime.py:613`）。`rg` 全仓命中只有定义点。
2. **`queue_mode` 的 `"all"` 排空模式**（:39 类型、:62 字段、:249-253 分支）：
   没有任何构造传 `"all"`——生产与测试全部用默认 `"one_at_a_time"`；
   `agent_runtime.py:189-234` 只用 `clear_queues`/`replace_messages`/`steer`/
   `follow_up`/`queued_messages`。应用层需要重新排队时显式走 `steer`/`follow_up`。
3. **`after_tool_call` 钩子**（`loop.py:48-51` 类型、:90 参数、:471-472 调用、
   经 `_run_parallel_tool_batch`（:303-304）/`_execute_tool_call`（:415-416）透传、
   `harness.py:65` 字段 + :205）：全仓零调用点，唯一生产构造
   `agent_runtime.py:139-140` 显式传 `None`；`adapters/tool_adapter.py:45`
   文档注释明说 runtime 故意不注入它（策略归 tooling middleware）。
   `before_tool_call` 只有一个测试引用（`tests/core/test_harness.py:275`），
   生产走 `before_tool_calls`（复数，预算检查路径，`agent_runtime.py:338`）。

## Proposal

1. 删除 `has_queued_messages`/`pop_latest_follow_up`/`pop_latest_steering`/
   公共 `append_interrupted_tool_results`/`pending_message_count`/
   `QueuedMessages.count`（内部 `_append_interrupted_tool_results` 保留：
   `harness.py:188/:221` 实际使用）。
2. 删除 `QueueMode` 类型、`queue_mode` 字段与 `"all"` 分支（排空恒按
   popleft 单条处理）；删除集成测试 :613 的断言。
3. 删除 `AfterToolCall` 类型、`after_tool_call` 参数/字段/透传/调用点；
   顺带删除 `before_tool_call`（其唯一测试可改经 `before_tool_calls`）
   或将 `before_tool_call` 列为可选；同步 `tool_adapter.py:45` 的文档注释。

## Why not keep it

这些是"未来的 Pi 宿主"很可能需要的通用面——但 API 面应该与现存宿主成正比：
今天唯一宿主是 Agent Runtime 与测试，两者都用不到单条弹出、`all` 排空与
per-tool 钩子。工具执行后策略已经在 `ToolRuntime` middleware 实现
（`tooling/middleware.py`），通用的 post-tool 钩子若将来真要加，从
`before_tool_calls` 同级再加回即可。

## Acceptance criteria

- `rg -n "queue_mode|pop_latest|has_queued_messages|append_interrupted_tool_results|pending_message_count|after_tool_call|before_tool_call" lion_code tests` 零命中（保留 `before_tool_calls` 复数路径）。
- `tests/core/test_harness.py` 与 `tests/integration/test_agent_core_runtime.py` 全绿；
  steering/follow-up 的集成行为不变（`steer`/`follow_up`/`clear_queues` 保留）。
- 全量可跑 unittest 通过；`git diff --check` 干净。

## Risks

- `QueuedMessages` 是 `application/ports.py` 投射边界的一部分（应用层读
  `queue_snapshot()`），只删 `count` 属性不删类型，风险低。
- `before_tool_call` 若保留其测试则一并保留，避免为了删 3 行改写既有用例；
  本提案将其列为可选项。

## 落地

- 提交: `84c408cbfc2a7e70e9ae1a386fbaeb7e2702907c`（squash merge）
- PR: #49（标题：refactor: 裁剪通用 Harness 的无宿主面（队列原语、all 排空、单工具钩子））
- 门禁证据: 定向测试全绿（排除 5 个已知环境性/既有失败：test_coding_session_ports、test_composition_profiles::test_all_profiles_return_meta_facade、test_capability_migration::test_session_participant、test_agent_core_runtime::test_plan_clear、test_cli::test_repl_routes_generic_command）；CI Quality gates 已通过（2026-08-18）。
