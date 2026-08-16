# PR7b MCP Total Removal — Design

## 1. Boundary decision

MCP 不再是 Full Product 的可选 Capability，也不作为未来 Profile extension 保留。删除目标是整个
可达链和专用实现，而不是把 `mcp_enabled` 默认改为 false、保留未接线模块或引入 NullMcpManager。

## 2. Current and target graph

Current:

```text
Agent / AgentConfig.mcp_enabled
  -> build_agent_composition(CAP_MCP)
     -> McpManager + McpLifecycleState
     -> McpCapability.before_turn
     -> discover remote tools -> ToolRegistry
     -> ToolEnvironment owns disconnect_all
        -> SessionLifecycle.close
        -> child_view shared with SubAgent
```

Target:

```text
Agent / Composition
  -> ToolRegistry + CapabilityRegistry
  -> Skill / SubAgent / Plan / Memory
  -> SessionLifecycle closes Core + Capability resources

MCP client / adapter / capability / environment
  -> deleted
```

## 3. Composition and facade deletion

- Composition Root 删除 MCP imports/constants/branches 和 graph fields；`PRODUCT_CAPABILITIES` 在 PR7b
  暂时只剩 Skill/SubAgent/Plan/Memory，PR7c 再由 Profile 取代。
- `AgentConfig` 删除 `mcp_enabled`，`AgentDependencies` 删除 `tool_environment`。
- `AgentComposition`、`_FoundationGraph`、`_CapabilityGraph` 与 `Agent` 删除 manager/state/capability/
  environment 引用和断言。
- `McpLifecycleState` 从 Composition ports 删除；MetaAgent 不再通过 `mcp_enabled=False` 证明 Bare，
  而由空 CapabilityRegistry 和 caller-owned registry 直接证明。

## 4. ToolEnvironment deletion

`ToolEnvironment` 当前只封装 `McpManager` 的父子共享与 close ownership。删除它后：

- `SubagentFactory` 不再接收 environment，也不创建 child view；只传递经 `select_tools()` 复制的 registry。
- `SessionStatePort` 不再保存 tool environment。
- `SessionLifecycle.close()` 删除最后一层 environment close，Capability resources 继续由
  `CapabilityRuntime.close()` 统一释放。
- `Agent.tool_environment` 与测试 injection seam 直接删除，不留通用资源容器；未来确有第二种外部资源时
  通过 Capability `resources` slot 组合，而不是预留空 God Object。

## 5. Dedicated implementation deletion

删除 JSON-RPC subprocess client、remote tool adapter、MCP Capability 和对应测试。通用
`ToolRegistry`、`LionTool`、ToolRuntime middleware 不增加 MCP namespace deny/allow 分支；系统只是不再
产生或发现 MCP 工具。

## 6. Residual cleanup and architecture checks

- 更新 CLI/Application/TUI/session/runtime comments，删除“关闭 MCP”“MCP 初始化”等过时契约。
- 更新 benchmark worker：不再接受/断言 `mcp_enabled`，安全性由 Profile 之前的显式产品图保证。
- 更新 Dream retained code中的提示/构造调用，只移除 MCP 词汇和参数，不恢复 Supervisor 产品可达性。
- 删除 MCP 直接测试，收紧 AST/filename/import strong negatives；同步 import-linter、quality baseline、
  ownership 和 backend specs。

## 7. Compatibility and rollback

项目不保留向后兼容。`Agent(mcp_enabled=...)`、`AgentDependencies(tool_environment=...)`、MCP modules 与
exports 直接消失。PR7b 整体回滚即可恢复 PR7a 的 MCP 链；PR7c 不承担 MCP migration。
