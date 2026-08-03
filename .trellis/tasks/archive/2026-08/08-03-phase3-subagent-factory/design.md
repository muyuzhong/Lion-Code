# 三阶段-3：`subagent_factory` 设计

## Boundary

`SubagentFactory` 是一个轻量的组合对象：它根据父 Agent 的动态配置为子 Agent 选择受限 Registry 并构造实例。它不执行子 Agent、不会发出 UI 状态、不会累计令牌，也不拥有 MCP 或会话资源。

```text
Agent tool / Skill fork
        │
        ├─ 状态通知、run_once、计费、错误文本、close（保留在 Agent）
        │
        └─ SubagentFactory
             ├─ get_sub_agent_config / Skill allowed_tools → ToolSelectionPolicy
             ├─ select_tools(parent.tool_registry, policy)
             └─ 局部导入 Agent 并构造 child
```

## Host Contract

工厂依赖一个仅包含下列能力的 `SubagentFactoryHost` Protocol：

- `tool_registry`：供 `select_tools()` 生成共享工具对象、独立激活状态的 child view。
- `tool_environment`：供 child 获取 `child_view()`，从而共享 MCP manager 但不拥有其生命周期。
- `_child_api_kwargs()`：每次构造时读取当前模型、凭证和终端输出设置。
- `_child_permission_mode()`：保留 `plan`/`auto` 向下传递以及其他模式的既有语义。

该协议避免工厂依赖完整 `Agent` 类型；类型检查中的前向引用不应触发运行时导入。

## Construction Paths

- `create_for_agent_type(agent_type)`：调用既有 `get_sub_agent_config()`，按其 `ToolSelectionPolicy` 创建 child。
- `create_for_skill(system_prompt, allowed_tools)`：将 Skill 的 `allowed_tools` 转成既有策略；缺省时排除 `agent` 与 `schedule_wakeup`。
- 私有构造方法在函数体内 `from .agent import Agent`，然后传递既有 API 参数、工具 Registry、`ToolEnvironment.child_view()`、`is_sub_agent=True` 与子权限模式。

## Compatibility and Risks

- `Agent` 的 monkeypatch 仍可在调用懒导入前替换 `lion_code.agent.Agent`；现有行为测试应继续验证真实构造参数。
- 工厂不得缓存 API 参数、权限模式或 child view，因为 `/model` 和权限模式可在父实例生命周期内变化。
- 若导入循环、测试 patch 或输出/关闭顺序发生回归，回滚仅需删除工厂委托并恢复两处原有构造逻辑。
