# PR7a Supervisor Product Detachment — Design

## 1. Boundary decision

PR7a 是纯删除式职责迁移：Full Product 不再选择或持有 Supervisor 对象，产品命令面也不再
提供对应入口。独立 runtime 代码保留是为了后续 re-home，不代表仍属于 Agent 产品图。

不创建 `SupervisorConfig`、`autonomy=False`、NullSupervisor 或 lazy fallback。被移除的 facade
方法直接删除。

## 2. Current call graph and target graph

Current:

```text
Agent
  -> build_agent_composition(PRODUCT_CAPABILITIES)
     -> Capability: MCP / Skill / SubAgent / Plan / Memory
     -> Supervisor: Dream / Autonomy / Learning / ProviderModelQuery
  -> Agent supervisor delegates
  -> REPL / Application / TUI commands
```

Target:

```text
Agent
  -> build_agent_composition(PRODUCT_CAPABILITIES)
     -> MCP / Skill / SubAgent / Plan / Memory only

autonomy_runtime / dream / learning_runtime
  -> no production caller until a future Supervisor composition owns them
```

Kernel、Harness runtime、CapabilityRegistry 与 MetaAgent 不改变控制流。

## 3. Composition deletion

- 删除 `CAP_DREAM`、`CAP_AUTONOMY`、`CAP_LEARNING` 及相关 import。
- `PRODUCT_CAPABILITIES` 暂时保留为 PR7a 到 PR7b 的短生命周期名称，但内容只含 Capability；
  PR7b 会由 Profile 取代该常量。
- `_SessionGraph` 只返回 Memory coordinator；删除 Supervisor model query、autonomy、learning 字段。
- `_build_session_graph()` 不再接收只供 Dream child 使用的 `child_config`，不再构造 identity-to-Dream
  factory；Memory 直接解析 identity 并构造自己的 coordinator。
- `AgentComposition` 删除 Supervisor 字段；`Agent` 删除相应断言和赋值。

## 4. Memory/Dream separation

`SessionMemoryCoordinator` 的 Memory、Session 状态、overlay、语义抽取与命令能力都不依赖 Dream。
实现删除的耦合点是构造参数 `dream_runner`、`status_callback`、`refresh_context` 与 `dream()` /
refresh helper；级联地，Composition 的 status_sink 门控不再包含 CAP_MEMORY，
`AgentComposition`/`Agent` 的 `refresh_dynamic_context_enabled` 门面链一并删除（其唯一读者
是 Dream 刷新路径）。

`DreamCoordinator`、plan parser、restricted child factory 与直接单元测试保留，不通过 Memory 或
Agent 自动获得生产可达性。未来 Supervisor re-home 必须自行组合 Dream 的 Memory snapshot view。

## 5. Product surface deletion

- `Agent`: 删除 dream/learn/goal/loop/auto/model-query 代理与状态视图；`set_confirm_fn()` 只更新
  通用 confirmation owner。
- REPL: 删除命令解析、帮助文本以及 signal handler 的 stop-loop/stop-goal 调用。
- Application/TUI: 删除 `dream_requested`、`CodingSessionBackend.dream()`、session dispatcher 与
  TUI pending-command 分支；未知 `/dream` 走既有 unknown-command 路径。
- SubAgent tool selection: 删除对 Supervisor 临时工具 `schedule_wakeup` 的特殊排除；该工具不在
  常驻 registry 中。

## 6. Tests and re-home policy

- 增加/收紧架构断言：Composition Root 不出现 Supervisor import/symbol；Full Product 图无相关字段。
- Agent-driven Autonomy 行为测试统一使用
  `_REHOME = "等待 Supervisor composition 重新接入 Autonomy"` 并 skip；不删除测试内容。
- Dream/Learning/Autonomy 独立 runtime 单元测试继续运行，证明保留代码仍自洽。
- MetaAgent strong-negative 清单移除已不再属于 Composition Root 的 patch target。
- CLI/Application/TUI 测试改为验证命令已消失或走 unknown-command。

## 7. Compatibility and rollback

项目不保留向后兼容；旧 Agent Supervisor API 与命令直接消失。单一回滚点是 PR7a 中文提交；
回滚后恢复 master 上的旧产品接线，不影响 Bare MetaAgent。
