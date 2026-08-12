# 技术设计

## 1. 运行时预算边界

`AgentRuntimeCoordinator` 仍通过 `LionAgentRuntime` 组装唯一的 `AgentHarness`，但不再向这个 Coordinator-owned Harness 传入 `max_turns`。通用 `run_agent_loop` 的计数器属于可复用 Harness 的防失控机制，不是本 Agent 的 Usage turn 账本；它会把最终文本和排队 follow-up 也计入迭代次数，与 Usage 规范的 Core tool boundary 不一致。

Coordinator 已有的 `before_core_tool_calls` 会在工具边界调用 `UsageLedger.record_turn()`，再用共享 `BudgetPolicy` 检查快照。因此预算语义只在一个 Owner 上生效：工具边界仍按 inclusive `>=` 停止，纯文本和队列调度不额外增加 usage turn。`LionAgentRuntime` 的 `max_turns` 参数及独立 Harness 调用语义保留，避免把通用 Core API 与 Agent composition 混为一谈。

## 2. 外部取消命令路由

在 `LionAgentRuntime` 增加一个可选的无参取消命令回调 `cancel_callback`：

- standalone Runtime 没有回调时，`cancel()` 继续委托 `AgentHarness.cancel()`，由 Harness 自己拥有并取消本地 token。
- Agent composition 传入 `ExecutionControl.cancel`。此时 Harness 仍只保存 `CancellationView` 供 Provider/Tool 读取，Runtime 的公开取消命令通过回调回到唯一 Owner。

这只增加命令路由，不保存取消状态、不创建新 token，也不把 `ExecutionControl` 类型耦合到可复用 Runtime 的构造签名。取消回归测试同时覆盖同一个 `ExecutionControl` 的状态变化和运行中 FakeProvider 的 aborted 结果。

## 3. CapabilitySpec 容器归一化

`CapabilitySpec.__post_init__` 使用 `object.__setattr__` 在 frozen dataclass 初始化阶段将六个序列字段转为 tuple，将 `requires` 转为 frozenset。这样字段的公开容器类型满足 SPI 合约，且外部传入容器后续变化不会影响 spec 或 Registry 的缓存顺序。元素对象本身的生命周期/可变性不在本次 SPI 字段不变性范围内，Registry 仍只负责贡献聚合和资源关闭。

## 4. Capability 测试 fake

复用现有测试中构造 `LionTool` 的模式，为 `_FakeToolSource` 保存由名称生成的最小 `LionTool`，`tools()` 返回 `Sequence[LionTool]`。需要比较名称的断言改为读取 `tool.name`，不放宽生产 `ToolSource` 协议，也不引入仅供测试的 cast。

## 5. 影响与回滚

生产改动限定在 `lion_code/agent_runtime.py` 和 `lion_code/capabilities/types.py`；回归测试限定在 Runtime/Capability 现有测试文件。若验证失败，可单独回滚本次中文提交，不涉及 JSONL 会话格式、Provider 协议或数据迁移。
