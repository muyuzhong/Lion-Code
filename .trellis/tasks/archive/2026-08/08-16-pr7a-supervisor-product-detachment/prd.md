# PR7a Supervisor Product Detachment

## Goal

从 Lion 当前 Full Product 的 Composition Root、`Agent` facade 及 CLI/Application/TUI 产品路径
移除 Autonomy、Dream、Learning，使后续 Profile 不可能把 Supervisor 行为伪装成 Agent Capability。

## Background

- 最新 `origin/master@ab3261d` 的 `PRODUCT_CAPABILITIES` 同时包含 MCP/Skill/SubAgent/Plan/Memory
  与 Dream/Autonomy/Learning，违反四层归属中 Capability 与 Supervisor 的边界。
- `AgentComposition`、`_build_session_graph()` 与 `Agent` facade 持有 Supervisor 对象；REPL 暴露
  `/learn`、`/goal`、`/loop`，Application/TUI 暴露 `/dream`。
- Memory 当前被迫接收 `DreamRunner`，导致选择 Memory 也会构造 Dream；PR7a 必须先解除这条隐藏依赖。

## Requirements

- Composition Root 不再 import、构造或返回 `AutonomyRuntime`、`DreamCoordinator`、
  `RestrictedDreamAgentFactory`、`LearningRuntime`、`ProviderModelQuery` 等仅服务 Supervisor 的对象。
- Full Product 的 capability 选择只保留 MCP、Skill、SubAgent、Plan、Memory；删除 Dream、Autonomy、
  Learning capability 常量与选择分支。
- `SessionMemoryCoordinator` 删除 `DreamRunner` 构造依赖及 `/dream` 委托；Memory 可独立构造。
- `Agent` 删除 Supervisor 字段、断言、代理属性和公开/私有委托方法，不保留 alias、fallback、
  lazy construction 或“不可用”兼容方法。
- REPL、Application、TUI 删除 `/dream`、`/learn`、`/goal`、`/loop` 的命令、帮助文本、结果字段、
  backend port 与调度分支；取消流程不再调用 Supervisor stop 方法。
- 独立的 `autonomy_runtime.py`、`dream.py`、`dream_adapter.py`、`learning_runtime.py` 及其直接单元测试
  暂时保留，供未来 Supervisor re-home；产品集成行为测试按 `_REHOME` 规则显式 skip。
- 删除 Capability/SubAgent 产品路径中只为 `schedule_wakeup` 保留的过滤规则；Supervisor 自身的
  临时工具实现不在本 PR 重建。
- 不引入 Profile、Supervisor facade、scheduler、兼容层或新依赖。

## Acceptance Criteria

- [ ] 构造 Full Product 时 monkeypatch Supervisor constructor 为失败函数也不会被调用。
- [ ] `AgentComposition` 与 `Agent` 实例不再含 autonomy、dream、learning、Supervisor model-query 字段。
- [ ] `Agent` 的产品 facade 不再暴露 dream/learn/goal/loop/auto 相关 API。
- [ ] 选择 Memory 时不构造 Dream，且 `SessionMemoryCoordinator` 无 Dream protocol/field/method。
- [ ] CLI/Application/TUI 不再识别或宣传 `/dream`、`/learn`、`/goal`、`/loop`。
- [ ] Kernel/Harness 未新增 Supervisor-specific branch；Composition Root 的 Supervisor import 为零。
- [ ] 等待 re-home 的 Agent 集成测试带统一 `_REHOME` 原因并 skip；独立 Supervisor runtime 测试仍执行。
- [ ] 定向测试、架构门禁、全量测试及质量基线门禁通过；既有噪音单独报告。

## Out of Scope

- 删除或重写独立 Supervisor runtime 实现。
- 建立新的 Supervisor composition/facade/scheduler。
- Minimal/Coding/Full Profile、execution backend 或 permission strategy。
- 恢复 PR1 延期的 Memory per-turn lifecycle 与 provider-refresh 行为。

## Dependency and Rollback

- 本任务先于 PR7b；PR7b 必须基于本任务提交，不能在同一提交中混入。
- 回滚 PR7a 应整体恢复 Supervisor 产品接线，不影响 PR0-PR6 Bare MetaAgent 边界。
