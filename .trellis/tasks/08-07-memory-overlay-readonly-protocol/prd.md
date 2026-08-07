# Memory Overlay 只读 Protocol：类型层面禁止 Harness 访问

## Goal

将 Memory Overlay 对 Harness 的隔离从 AST 黑名单（禁止 `AgentHarness` 引用、
禁止 mutation 方法调用）提升到类型层面：Memory 层的接口只接收不可变消息
快照和只读 Protocol，使其在对象能力层面根本拿不到 Harness 实例。

## Background

第四阶段架构边界审查点 4 指出：

> 目前禁止的方法主要是 `clear_queues`、`follow_up`、`replace_messages`，
> 但仍可能通过 `harness.config`、`harness._messages`、`messages.append(...)`
> 绕过。最终解决方式不是不断扩充 AST 黑名单，而是给 Memory 层只传入
> 不可变消息快照 `tuple[AgentMessage, ...]` 以及只读 Protocol。

当前状态：
- `MemoryContextInjector.inject()` 已接收 `Sequence[AgentMessage]` 并返回新列表，
  不修改输入（行为测试 `test_provider_does_not_retain_conversation_across_requests` 验证）。
- AST 测试 `test_memory_overlay_code_cannot_mutate_harness_messages` 禁止
  `AgentHarness` 引用和 mutation 方法调用。
- **缺口**：类型系统不强制——Memory 层的接口签名没有显式拒绝 Harness 类型，
  新代码可以在不触发 AST 扫描的情况下通过鸭子类型访问 Harness 属性。

## Requirements

### R1. 只读消息快照

- R1.1 `MemoryContextInjector.inject()` 的 `messages` 参数类型从
  `Sequence[AgentMessage]` 收紧为 `tuple[AgentMessage, ...]`（或
  `Sequence[AgentMessage]` 配合运行时 `frozenset`/`tuple` 转换）。
- R1.2 调用方在传入前将可变 `list` 转为 `tuple`，确保 Memory 层
  拿到的是不可变快照。

### R2. 只读 Protocol

- R2.1 定义一个 `ReadOnlyMessageSource` Protocol（或类似名称），
  只暴露 `messages` 属性（返回 `tuple[AgentMessage, ...]`），
  不暴露 `clear_queues`、`follow_up`、`replace_messages` 等 mutation 方法。
- R2.2 Memory 层（`memory_runtime/` 和 `session_memory_coordinator.py`）
  的公共接口只接收 `ReadOnlyMessageSource` 或 `Sequence[AgentMessage]`，
  不接收 `AgentHarness`。

### R3. AST 测试保持

- R3.1 现有 `test_memory_overlay_code_cannot_mutate_harness_messages`
  继续作为回归 guard。
- R3.2 新增测试验证 Memory 层接口签名不包含 `AgentHarness` 类型注解。

## Acceptance Criteria

- [ ] `MemoryContextInjector.inject()` 接收不可变消息快照（`tuple` 或等效）。
- [ ] Memory 层公共接口不接收 `AgentHarness` 类型参数。
- [ ] 现有 AST 测试和行为测试继续通过。
- [ ] 全量 pytest 通过，ruff/format/mypy 基线不恶化。
- [ ] import-linter 5 条合同 KEPT。

## Out of Scope

- 不改变 Memory 的召回策略、注入格式或预算逻辑。
- 不重构 `AgentHarness` 本身的接口。
- 不移除现有 AST 黑名单测试（它作为回归 guard 保留）。
