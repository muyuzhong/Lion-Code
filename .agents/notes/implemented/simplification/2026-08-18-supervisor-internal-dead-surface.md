# Agent Note: 清理 Supervisor 平面内部死面（run_timeout / should_retry cancelled / 结果与持久化冗余字段）

- Status: proposed
- 日期: 2026-08-18
- 范围: `lion_code/supervisor.py`、`tests/test_supervisor.py`、`tests/architecture/test_supervisor_plane.py`

## 背景

Supervisor 与产品脱离是 **PR7a 的刻意决策**（见 `.trellis/tasks/08-16-pr7b-mcp-total-removal/prd.md`：
"在 PR7a 已完成 Supervisor 产品脱离的基线上……"），PR10 完整落地控制平面，
README §5 与 :493 明文说明长期任务由外部 Supervisor 显式恢复，架构测试强制
composition root 不得构造 Supervisor（`tests/architecture/test_composition_root.py:207-230`）。
因此本笔记**不**提议改动该平面的存在与否，只清理决策之外累积的死面——以下每项的
共同证据模式是：`rg` 全仓命中仅限 `supervisor.py` 自身或测试，零生产调用者。

## Problem

1. **`Supervisor.__init__(run_timeout=...)`**（`supervisor.py:568-582` 参数+校验，
   :582 保存，:840 转发给 `AgentPort.run(timeout=...)`）：`rg "run_timeout"` 全仓
   零命中——没有调用者，测试也从不传它（`tests/test_supervisor.py` 全部 9 处构造）。而
   `AgentPort.run` 的真实实现（`agent_runtime.py:778-820`：`loop.call_later` +
   `abort()` + `task.cancel()` + stop reason `"timeout"`）已经端到端实现了超时；
   Supervisor 再转发一层只是重复一套 timeout/abort 机制。
2. **`RetryPolicy.should_retry(*, cancelled=False)`**（`supervisor.py:467-474`，
   唯一调用点 :958-961 恒传 `False`）：调用方结构保证 cancelled 结果在到达
   `should_retry` 之前就返回（`_apply_outcome` :935 先判 `_mark_cancelled`），
   该参数按构造不可达。
3. **`SupervisorResult.goal_id`（:492-494）与 `.error`（:512-514）**：纯
   `state` 透传属性，`rg "result.goal_id|result.error"` 在 Supervisor 关联代码零消费
   （命中的 `error` 全是 `AgentRunResult`/hooks 别的对象）。
4. **`SupervisorState.next_delay_seconds`**（:103 字段清单、:194-205 校验、
   :252 字段、:265/:284 to/from dict、:314-326 严格校验；写入点 :699/:710/:953/
   :975/:988/:1002）：没有任何控制流读取它——`_wait_for_retry`（:716-721）只驱动
   `next_run_at`。它与 `next_run_at`、`retry_count` 完全重复（:975-976 恒成对写
   `next_delay_seconds=delay` 与 `next_run_at=now+delay`），只被
   `tests/test_supervisor.py:136,179,297` 与
   `tests/architecture/test_supervisor_plane.py:55` 当作 checkpoint 形状断言。
5. **`_CANCELLED_STOP_REASONS` 含 `"cancelled"`**（:550）：真实 Agent 的 stop reason
   全集在 `agent_runtime.py`（:475 `"aborted"`、:477 `"model_error"`、:479
   `"completed"`、:488 budget kinds、:706 `"aborted"`、:818-820 `"timeout"`）中不存在
   `"cancelled"`；测试 fake 在取消时也返回 `"aborted"`（`tests/test_supervisor.py:80`）。
   `core/events.py` 的 `cancelled` 事件类型是另一个命名空间（:916 按事件类型匹配，
   不经此集合）。集合中的 `"cancelled"` 不可能被匹配。

## Proposal

1. 删除 `run_timeout` 参数、校验块、`self._run_timeout`，:840 显式传 `timeout=None`。
2. 删除 `should_retry` 的 `cancelled` 参数与 `not cancelled` 首项，:961 去掉实参。
3. 删除 `SupervisorResult.goal_id` 与 `.error` 两个透传属性；保留
   `status/attempt/session_id/stop_reason/succeeded`（测试在使用）。
4. 从 `SupervisorState` 删除 `next_delay_seconds`：字段、`_STATE_FIELDS`、
   `to_dict/from_dict`、`_validate_state_timestamps` 中的校验、全部写入点；
   同步改 `tests/test_supervisor.py:179` 的期望字段集、:297 fixture、
   `tests/architecture/test_supervisor_plane.py:55` 的 `_CONTROL_FIELDS`。
5. `_CANCELLED_STOP_REASONS` 收敛为 `frozenset({"aborted"})`。

## Why not keep it

`run_timeout` 看起来像控制平面"天然的"定时参数，`next_delay_seconds` 像"自然的"
重试元数据（README.md:247 称 checkpoint 含 retry metadata），`.error` 像"天然的"
结果字段——但没有任何消费路径，且 #1 与 Agent 已有超时机制重复、#4 与
`next_run_at`/`retry_count` 重复。#3/#5 是防某个从未出现的字符串/调用而存在的防御面。
`AGENTS.md` 原则 1（不保留向后兼容）+ 原则 2（最简单实现）下，删除是净减：五个裁剪
合计 ~60 行生产代码 + 测试与架构断言同步收缩，且 checkpoint 严格形状契约（
"只保存执行控制"）随之更精确。

## Acceptance criteria

- `rg -n "run_timeout|next_delay_seconds"` 全仓（除本文件）零命中；
  `rg -n "goal_id|\.error"` 在 supervisor 关联代码零新增消费。
- `tests/test_supervisor.py` 与 `tests/architecture/test_supervisor_plane.py` 全绿；
  全量可跑 unittest 通过；`git diff --check` 干净。
- Supervisor 状态机行为不变：`tests/architecture/test_composition_profiles.py:390-399`
  的构造与 `result.succeeded/session_id` 用例保持绿。

## Risks

- `SupervisorResult.error` 删除后，外部未来消费者需访问 `result.state.last_error`——
  一步之遥，且当前零消费者。
- 若未来某 Agent 实现选择用 stop reason `"cancelled"` 表达取消，#5 需改回——
  当前契约与所有实现（含测试 fake）都只用 `"aborted"`，风险即契约漂移，可接受。

## 附：观察（不构成提案）

`_observe_event`/`_RUNNING_EVENT_TYPES`（:536-549, :908-929）把
`compaction_started`/`turn_failed` 投影成 `phase="recovery"` 并逐事件写 checkpoint，
但没有任何控制流分支读该相位（:638 只分支 `retry_wait`），consumer 只有
`tests/test_supervisor.py:188-205`。它是架构断言过的持久化遥测
（`tests/architecture/test_supervisor_plane.py:111-120`，four-layer-ownership.md:50
明言 recovery 属 Supervisor 拥有）。若未来有 checkpoint 巡检工具可留；若确认
checkpoint 只作执行控制（README:247），可走独立提案删除。

## 落地

- 提交: `4b76c1e`
- PR: #56（标题：refactor: 清理 Supervisor 平面内部死面（run_timeout / should_retry cancelled / 冗余结果与持久化字段））
- 门禁证据: 定向测试全绿（排除 5 个已知环境性/既有失败：test_coding_session_ports、test_composition_profiles::test_all_profiles_return_meta_facade、test_capability_migration::test_session_participant、test_agent_core_runtime::test_plan_clear、test_cli::test_repl_routes_generic_command）；CI Quality gates 待绿。
