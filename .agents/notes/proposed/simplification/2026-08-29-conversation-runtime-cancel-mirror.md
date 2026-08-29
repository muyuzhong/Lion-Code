# Agent Note: 删除 ConversationRuntime 的取消镜像面（cancel/cancelled/cancel_callback）

- Status: proposed
- 日期: 2026-08-29
- 范围: `lion_code/runtime/conversation.py`、`lion_code/composition/agent_builder.py`、`tests/integration/test_agent_core_runtime.py`、`tests/runtime/test_agent_runtime.py`

## Problem

`ConversationRuntime` 上有一份与 `ExecutionControl` 完全重复的取消路径，生产零调用：

1. `cancel()`（`runtime/conversation.py:170-175`）、`cancelled` 属性（:177-180，直接读私有 `harness._cancellation`）、`cancel_callback` 参数（:47/:53）。
2. 生产取消链是 `MetaAgent.cancel`（`meta_agent.py:121-122`）→ `AgentRuntime.abort`（`runtime/agent.py:475-480`）→ `ExecutionControl.cancel`；`rg` 验证生产没有任何 `conversation.cancel(` 调用点（bridge/session/backend 全部走 `self._backend.cancel()` → `self._agent.cancel()`）。
3. `cancel_callback` 的唯一注入点是 `agent_builder.py:336`（`cancel_callback=execution.cancel`），但没有任何调用方走到该参数；`cancelled` 属性经 `harness._cancellation` 私有直穿，而生产读的是 `MetaAgent.cancelled`（`meta_agent.py:124-126`，走 `execution.cancelled`）——同一事实两份读取面。
4. 消费者只有测试：`tests/integration/test_agent_core_runtime.py:627`（`conversation.cancel()`）与 `tests/runtime/test_agent_runtime.py:236`。

## Proposal

1. 删除 `conversation.py:170-180` 的 `cancel()`/`cancelled` 与 `cancel_callback` 参数（:47/:53）。
2. 删除 `agent_builder.py:335-336` 的 `cancel_callback=execution.cancel` 注入。
3. 改写两个测试用例（:627、:236）走 `execution.cancel`/`abort` 路径。

## Why not keep it

「生产有两份取消事实，只有 execution 那份被读」正是 `state-ownership.md` 单所有者契约（取消令牌归 `ExecutionControl`）的违反面；该 Runtime 的窄端口风格不允许经私有 `harness._cancellation` 直穿。按「一个事实一个表示」删除。

## Acceptance criteria

- `rg -n "conversation\.cancel\(|\.cancelled\b|cancel_callback" lion_code/` 仅剩 `execution.cancelled`/`MetaAgent.cancelled` 合法命中。
- `tests/integration/test_agent_core_runtime.py`、`tests/runtime/test_agent_runtime.py` 全绿。

## Risks

- 若未来宿主想从会话对象直接取消而不触碰 AgentRuntime，需重建该桥——恢复成本 6 行；当前唯一宿主（MetaAgent/Adapter）显式走 abort，无此需求。