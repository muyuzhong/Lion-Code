# 修复运行时预算、取消与 Capability 类型边界

## Goal

修复 `muyuzhong/capability-spi-foundation` 相对 `origin/master` 审查中确认的四个问题，使运行时的预算与取消命令回到既有 Owner，保证 `CapabilitySpec` 的容器字段真正不可变，并让 Capability 测试遵守 `ToolSource` 的类型契约。

## Background and confirmed facts

- `AgentRuntimeCoordinator` 当前把 `max_turns` 传给通用 `run_agent_loop`。该循环按 Provider/tool-loop 迭代计数，而 Usage 规范要求 Runtime 只在 Core tool boundary 记录 turn；最终文本和排队 follow-up 不应被通用计数器提前截断。证据：`lion_code/agent_runtime.py:329`、`lion_code/core/loop.py`、`.trellis/spec/backend/usage-ownership.md` 的 Core tool boundary 约定。
- Agent composition 将 `ExecutionControl.cancellation` 这个只读 View 注入 `LionAgentRuntime`。`AgentHarness.cancel()` 只有在拥有本地 token 时才执行取消，因此 `LionAgentRuntime.cancel()` 在 Agent 运行时中不会触发真正的取消命令。证据：`lion_code/agent_runtime.py:115-139,188-190`、`lion_code/core/harness.py:81-86,129-131`、`.trellis/spec/backend/runtime-boundaries.md` 的取消 Owner 约定。
- `CapabilitySpec` 是 frozen dataclass，但 `__post_init__` 没有把外部传入的 list/set 归一化为 tuple/frozenset；注册后外部容器的变化可以绕过顺序缓存。证据：`lion_code/capabilities/types.py:97-133`、`.trellis/spec/backend/capability-spi.md` 的不可变性约定。
- `tests/capabilities/test_capability_registry.py` 中 `_FakeToolSource.tools()` 返回 `list[str]`，不符合 `ToolSource -> Sequence[LionTool]`，导致 `mypy lion_code tests` 在 Capability 测试处报错。证据：`lion_code/capabilities/types.py:35-43` 和该测试辅助类。

## Requirements

1. **预算边界**：Coordinator 运行时不得再用通用 Core loop 的 `max_turns` 计数器限制对话；继续由已有 Usage Ledger 在 Core tool boundary 记录 turn，并由已有 `BudgetPolicy` 判断边界。保留 `AgentHarness` 独立调用时已有的通用 `max_turns` 能力。
2. **取消命令**：当 `LionAgentRuntime` 使用外部 `CancellationView` 时，公开的 `cancel()` 必须调用 `ExecutionControl` 的取消命令 Owner；独立构造且没有外部 Owner 的 Runtime 仍使用 Harness 自有 token。不得复制取消状态或增加第二个 token。
3. **CapabilitySpec 不可变容器**：构造时把所有序列字段归一化为 tuple，把 `requires` 归一化为 frozenset；后续修改调用方传入的 list/set 不得改变已构造 spec 或 Registry 的缓存结果。
4. **测试类型契约**：把 Capability 测试 fake 改为返回真实的 `LionTool` 序列，并保留原有注册、聚合和顺序断言的行为覆盖；不得通过 `cast` 或放宽生产协议规避类型错误。
5. **回归覆盖**：为预算 follow-up、外部取消、Capability 容器归一化分别增加最小回归测试；测试应使用现有 FakeProvider 和项目内工具模型，不访问真实 Provider。

## Constraints

- 不引入兼容层、fallback、迁移脚本或新的状态 Owner。
- 不修改通用 `run_agent_loop` 的公共语义，不重写 Usage/Budget 体系，不扩展 Capability SPI 范围。
- 保留工作区中与本任务无关的 Trellis、AGENTS 和配置改动，不进行宽范围 stage 或 destructive git 操作。
- 源码注释使用中文；只在说明不变量或设计原因时补充注释。

## Acceptance Criteria

- [x] 含一次 tool turn、一次最终文本、随后排队 follow-up 的 Coordinator 运行，在预算仍有余量时可以继续消费 follow-up；精确达到 `max_turns` 的 tool boundary 仍由现有 BudgetPolicy 按 `>=` 停止。
- [x] Agent 组合的 `runtime.cancel()` 能使同一 `ExecutionControl` 变为 cancelled，并让当前 FakeProvider 运行收到 aborted 结果；取消后下一次运行仍由既有生命周期逻辑正常 reset。
- [x] `CapabilitySpec` 接收 list/set 输入后，字段类型分别是 tuple/frozenset；调用方继续修改原容器不会改变 spec、依赖解析顺序或聚合结果。
- [x] `_FakeToolSource` 返回 `Sequence[LionTool]`，Capability 测试保持通过；`mypy lion_code/capabilities tests/capabilities` 不再报告该测试辅助类引入的类型错误。
- [x] 受影响的 pytest、Ruff、compileall、import-linter、类型检查和 `git diff --check` 完成；已知的现有 Windows 临时目录权限问题单独记录，不伪装为代码通过。

## Out of scope

- 通用 `AgentHarness` / `run_agent_loop` 的独立 API 重新设计。
- 新 Capability、Capability Port、Provider SDK 或第三方依赖。
- 修复本任务前已存在的 `hooks.py` 等无关 mypy 基线错误。
- 清理或提交工作区中其他工程师已有的 Trellis/AGENTS 变更。

## Open questions

无。四个缺陷的目标行为由用户请求、现有运行时边界规范和 Usage/Capability 契约共同确定。
