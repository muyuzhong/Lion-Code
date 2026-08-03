# 三阶段-3：提取 `subagent_factory`

## Goal

把 `Agent` 中构造子 Agent 的重复职责迁入独立 `subagent_factory`，用懒导入避免新模块与 `agent.py` 的循环依赖，同时保持 Agent 工具和 Skill fork 的已有行为、权限与资源所有权不变。

## Confirmed Background

- `Agent._execute_agent_tool()` 当前根据 `get_sub_agent_config()` 选择工具，并构造、运行和关闭子 Agent。
- `Agent._execute_skill_tool()` 的 fork 分支重复了工具策略、子 Agent 构造、共享环境和关闭流程。
- 子 Agent 必须继承父 Agent 当前的模型/凭证、受限工具视图、`ToolEnvironment.child_view()`、`is_sub_agent=True` 与受限权限模式。
- 现有 `tests/tooling/test_skill_registry_view.py` 已覆盖共享 Registry/MCP 环境和关闭语义；`tests/tooling/test_tool_selection.py` 覆盖工具策略。

## Requirements

- R1：新增 `lion_code/subagent_factory.py`，由 `SubagentFactory` 统一处理内置 Agent 与 Skill fork 的工具策略和子 Agent 构造。
- R2：工厂只能通过窄 Host 协议读取父 Agent 的运行时构造参数、工具注册表、共享环境和子权限模式；不得复制或持有 Agent 的会话、记忆、Core 或 UI 状态。
- R3：工厂在实际构造子 Agent 时才局部导入 `Agent`；模块顶层不得导入 `lion_code.agent`，以避免循环导入。
- R4：`Agent` 保留工具入口、状态通知、运行结果计费、错误文本和 `close()` 的调用顺序；它只把构造和工具选择委托给工厂。
- R5：Agent 工具与 Skill fork 的子 Agent 必须继续共享父 Registry 中同一工具对象和同一 MCP manager 的非拥有视图；子 Agent 仍不能通过 `agent` 工具递归派生。
- R6：补充或调整聚焦测试，覆盖两条 fork 路径、当前凭证/权限传播和懒导入边界；不得因测试替身的 patch 目标变化而失去行为断言。

## Acceptance Criteria

- [x] AC1：`subagent_factory.py` 存在且其顶层导入不含 `lion_code.agent`；实际构造路径使用局部懒导入。
- [x] AC2：`_execute_agent_tool()` 和 Skill fork 分支均经同一工厂创建子 Agent，且不再在 `agent.py` 重复工具选择或 `Agent(...)` 构造。
- [x] AC3：既有共享 Registry、共享 MCP manager、非拥有环境、受限权限、令牌累计、成功/异常文本和关闭语义保持不变，并有测试证明。
- [x] AC4：聚焦测试、全量测试、编译、导入边界检查、差异检查和本子任务 Trellis 校验通过；静态检查相对基线没有恶化。
- [x] AC5：本切片不修改并行质量基线文件或 `docs/tui-migration-audit.md` 删除。

## Out of Scope

- 改变子 Agent prompt、工具授权规则、嵌套派生策略、MCP 生命周期或模型/凭证配置语义。
- 将子 Agent 的运行循环、状态通知或令牌累计迁入工厂；这些仍属于 `Agent` 协调职责。

## Open Questions

无。用户已确定继续完成路线，当前代码和测试已确定本切片的最小行为保持边界。
