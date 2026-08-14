# PR0 Event Stream Kernel Contract — Implement

## 目标

在 `core/events.py` 固化 Kernel 事件契约，补 4 个缺失事件（CompactionStarted/Completed、TurnFailed、Cancelled），加契约测试与 Supervisor 订阅契约测试。不做完整事件系统。

## 检查点

1. **声明契约事件**（`core/events.py`）
   - 新增 `CompactionStartedEvent` / `CompactionCompletedEvent` / `TurnFailedEvent` / `CancelledEvent`（WireModel + discriminated union）。
   - 加入 `AgentEvent` union。
2. **补最小发射点**（尽力而为，高风险可降级为纯声明 + 记录）
   - `TurnFailedEvent` / `CancelledEvent`：`core/loop.py::run_agent_loop()` 收尾，按 stop_reason / cancellation 发射。
   - `CompactionStartedEvent` / `CompactionCompletedEvent`：`agent_runtime.py` 压缩驱动点发射。
3. **新增契约测试** `tests/core/test_event_contract.py`：
   - 10 事件契约可表达（类型存在 + 判别字段 + 序列化 round-trip）。
   - Supervisor 订阅者只 import `core.events`/`core.provider_events` 公开类型，不触私有对象。
4. **回归**：现有事件相关测试全通过。

## 步骤

- [ ] 阅读 `core/events.py`、`core/loop.py`（run_agent_loop 收尾）、`agent_runtime.py`（compact_core_context_if_needed）、`application/events.py`（不动的参照）。
- [ ] 在 `core/events.py` 加 4 个事件类型 + union，保证 Pi 兼容（camel alias、discriminator）。
- [ ] 实现发射点（或记录降级原因）。
- [ ] 写 `tests/core/test_event_contract.py`。
- [ ] 跑验收命令（design §5）。
- [ ] 更新 spec（`runtime-boundaries.md` 或新增"Kernel 事件契约"小节）——见 child prd R3 / 父 prd 跨 child 验收。
- [ ] 提交（commit without asking）。

## 评审门

- 新增事件不影响现有事件字段/判别值。
- `lint-imports --no-cache` 通过（core 依赖方向正确）。
- Supervisor 订阅契约测试证明不依赖 Agent 私有对象。
- 若发射点降级为纯声明，在总结中说明"未发射"及其原因（PR 允许）。
