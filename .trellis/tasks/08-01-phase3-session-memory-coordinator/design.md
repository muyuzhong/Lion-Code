# SessionMemoryCoordinator 技术设计

## 1. 范围与父任务边界

本子任务只做三阶段-2 的职责提取：把项目级 Session Memory、项目指令
Overlay、Auto Memory 召回协调、Dream 入口和每轮短期状态更新从
`lion_code/agent.py` 迁入 `lion_code/session_memory_coordinator.py`。

父任务 `07-30-project-session-memory` 已经定义并实现了这些运行时不变量，
本子任务不得重新设计它们：

- Core Harness 的 canonical messages 仍是唯一活跃会话历史；Memory 只进入
  Provider 临时投影，不写入 JSONL。
- 项目指令、Session Memory、Auto Memory 的 Overlay 顺序保持
  `project -> session -> auto`，同一 chat 轮次固定同一快照。
- Session Memory 仍由 `SessionMemoryRepository` 按项目身份原子持久化，损坏
  文件只报告错误，不回写空状态。
- `/task`、`/session-memory`、`/handoff`、`/dream` 的 Agent 公共入口签名和
  结果文本保持不变。

## 2. 所有权与窄协议

`SessionMemoryCoordinator` 持有以下状态：

- `ProjectIdentity`、`SessionMemoryRepository`；
- 当前有效 Session Memory 及加载/上报错误状态；
- 项目 Overlay、当前轮 Overlay、`MemoryCoordinator`、
  `MemoryContextInjector` 和最近一次注入报告。

它通过 `SessionMemoryHost` Protocol 使用 Agent 的最小能力：

- `tool_context.cwd`、`_core_runtime.provider` 和当前 `model`；
- `_emit_notice`、`_emit_subagent_status`、`_child_api_kwargs`；
- `_core_runtime.messages`、`_session_repository`、`tool_registry` 和
  `tool_environment`，供现有 Dream 隔离 Agent 复用；
- 宿主提供的 `_extract_session_memory_semantics` 回调，用来保留测试替身
  和 side-query 边界；
- `_refresh_dynamic_system_context` 回调，用来在 Dream 修改 Auto Memory
  后刷新宿主系统提示词动态尾部。

Coordinator 不持有 Provider、TUI、Core 历史或全局 Service Locator。
Provider 相关的 `ProviderTextQueryService` 只在 Core Runtime 建好以后由
宿主绑定；构造期间使用 `None`，避免初始化顺序依赖。

## 3. Agent 兼容面

Agent 保留薄委托：

- 公共入口：`show_session_memory`、`show_active_task`、
  `switch_session_task`、`finish_session_task`、`create_session_handoff`、
  `dream`；
- 内部边界：项目/Session 重载、Overlay 构造、轮次快照、Session Memory
  轮后更新和 Dream 刷新。

Agent 通过属性委托继续暴露原有私有状态名，保证 Core 主路径、Dream
`getattr`、既有测试替身和 Provider 切换逻辑不需要同时迁移。带 setter 的
兼容属性允许测试替换 `agent._memory_coordinator` 或注入短期状态；对
`Agent.__new__` 构造的窄单元测试保留惰性回退，不影响正常初始化路径。

## 4. 生命周期与数据流

```text
Agent.__init__
  -> ToolContext / ProjectIdentity
  -> SessionMemoryCoordinator(query_service=None)
  -> Core Runtime / Provider
  -> coordinator.bind_query_service(current Provider)

chat
  -> coordinator.prepare_turn_snapshot(user input)
  -> Agent._prepare_core_context consumes coordinator.turn_memory_overlays
  -> coordinator.update_after_turn(canonical messages, semantic callback)

/dream
  -> coordinator.dream()
  -> DreamCoordinator(host Agent) 读取当前项目上下文并应用安全计划
  -> coordinator.invalidate_memory_context()
  -> host refreshes dynamic system prompt
```

`update_after_turn` 先从 canonical 工具事件提取确定性文件、验证和阻塞
证据，再通过宿主回调获取受限语义 patch；语义失败时仍保存确定性事实。
该顺序与父任务 Slice 3 保持一致。

## 5. 兼容性与回滚

- 不修改 `session_memory.py`、JSONL schema、Provider 协议、TUI 命令解析或
  `DreamCoordinator` 的安全校验。
- 若提取导致测试或运行时回归，可删除新模块并恢复 Agent 的原方法；
  本子任务的每个提交只包含提取相关文件，便于按提交回滚。
- 允许 `agent.py` 保留 Provider 切换时调用的
  `MemoryCoordinator.set_query_service`，但实际对象来自 Coordinator 属性，
  以保证旧 Provider 的预取取消语义不变。
