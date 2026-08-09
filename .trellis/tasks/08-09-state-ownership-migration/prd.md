# State Ownership 分阶段迁移

## Goal

把 Lion 中长期保存在 `Agent`、再手工复制给运行时消费者的可变状态，逐步收敛到唯一业务 Owner；`Agent` 最终只保留组合与门面职责。迁移必须分成可独立验证、可单独回滚的职责切片，不能演变为全项目重写。

## Background

- 当前 `SessionMemoryCoordinator`、`MemoryCoordinator` 已经拥有各自的 Memory 生命周期，本任务不改动其所有权。
- `ToolRegistry` 已经拥有 active tools 状态，本任务不改动其所有权。
- 当前仍存在 Session、Permission、Plan、Cancellation 和 Usage 的宿主字段或镜像字段；这些状态会通过 `Agent`、`ToolContext` 和 runtime host 协议传播。
- Provider 配置已由 `AgentLifecycle` 协调，但状态仍保存在 `Agent`。由于它还关联 ContextCompactor、ModelLimits、Memory query service 和 SessionRecorder，本轮四个交付切片不迁移 Provider 所有权。
- `read_file_state` 的目标 Owner 是 ToolRuntime/ToolExecutionState，但它不属于本轮四个 PR，作为后续独立切片处理，避免把无关职责塞进现有 PR。

## Requirements

### OWN-1：统一架构契约

所有子任务必须遵守并把以下规则写入可执行或可审查的架构契约：

1. Single Writer：一个 mutable state 只能有一个业务 Owner。
2. No Mirrored State：不得长期保存权威状态的可变副本。
3. Read through View：消费者通过只读 View/Protocol 获取状态。
4. Mutation through Command：跨字段不变量只能通过 Owner 的命令方法修改。
5. Derived State 不存储：能够从权威状态计算的值不得另存一份。

### OWN-2：按职责拆分交付

| 顺序 | 子任务 | 唯一职责 |
|---|---|---|
| 1 | `08-09-session-cancellation-ownership` | Session identity 与 Cancellation 所有权 |
| 2 | `08-09-permission-ownership` | PermissionState / PermissionView / PermissionController |
| 3 | `08-09-plan-runtime-ownership` | PlanState / PlanRuntime 与权限切换事务 |
| 4 | `08-09-usage-ownership` | UsageLedger / UsageSnapshot / BudgetPolicy |

每个子任务必须独立规划、验证、提交和归档；后续子任务以上一切片完成后的 `master` 为事实基线。

### OWN-3：保持既有产品不变量

- 只有一个 canonical Core history、一个活动 Provider、一个 SessionRecorder 和一条 JSONL 追加链。
- `/clear`、restore、Plan、abort、timeout、Autonomy、Memory、SubAgent、REPL 和 TUI 的对外行为保持不变。
- 不增加兼容层、迁移层、fallback 或重复状态容器；旧字段在对应子任务中直接删除。
- 不引入与当前四个 Owner 无关的新依赖。

## Acceptance Criteria

- [ ] 四个子任务均独立通过各自验收、中文提交并归档。
- [ ] Session、Permission、Plan、Cancellation 与 Usage 不再由 `Agent` 保存可变镜像。
- [ ] ToolRuntime 只通过只读依赖读取上述状态，不能直接修改它们。
- [ ] 跨域状态切换通过明确命令边界完成，Plan 与 Permission 不合并为一个 Domain。
- [ ] Memory、ToolRegistry、Provider configuration 与 read freshness 不被顺手重构。
- [ ] 架构测试能够阻止已删除镜像字段和多 writer 路径回归。
- [ ] 全量测试、compileall、import-linter、架构测试和 `git diff --check` 通过。

## Out of Scope

- ProviderManager / ProviderConfig 迁移。
- Memory 或 ToolRegistry 所有权调整。
- `read_file_state` 迁入 ToolExecutionState/ReadFreshnessTracker。
- Capability SPI、浏览器或 Sandbox 的新功能。
- 向后兼容别名或旧字段代理。
