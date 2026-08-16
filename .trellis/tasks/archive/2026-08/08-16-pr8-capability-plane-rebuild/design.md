# PR8 Capability Plane rebuild — Design

## 1. First-principles boundary

Capability Plane 的职责是"贡献"：Capability 通过窄 slot 把工具、prompt 片段、临时上下文、
生命周期观察贡献给 Agent；Kernel/Harness 只认识 slot 协议，不认识任何 Feature 符号。
本 PR 恢复 PR1 删除的 turn 驱动 Memory 行为时，不允许任何 Memory 符号回流到
`agent_runtime.py` / `session_lifecycle.py` / `core/`（`_BARE_GENERIC_FILES` AST 扫描强制）。

因此设计核心是回答两个问题：

1. Memory 需要的每个行为，落在哪个**既有 generic slot**？
2. 哪个行为**证明现有 slot 不够**、必须新增一个与 Memory 无关的 primitive？

## 2. Memory 行为 → slot 映射（核心设计）

PR1 前的 Memory 编排（从 commit `b8997d0^` 考证）与恢复方案逐条对应：

| PR1 前行为（coordinator 内联） | 恢复方案（Capability slot） |
|---|---|
| 压缩后 `turn_start_index = len(messages)`；`_prepare_turn_memory_snapshot(user_message)`（固定三层 overlay + 启动召回预取） | `MemoryTurnParticipant.before_turn(user_message)` |
| turn 结束 `_update_session_memory_after_turn(user, start_index)`（证据 + 语义 patch 保存），随后 `_build_turn_memory_overlays()` 刷新下一轮 | `MemoryTurnParticipant.after_turn()` |
| `prepare_core_context` 内 injector 注入 `<relevant-memory>`（带 token 预算，跳过未闭合 ToolCall） | **`ProjectionLayer`（新 slot）** 经 `CapabilityRuntime.project_context` 分发 |
| `abort()` 里 `cancel_pending()` | `after_turn` 内检查 CancellationView：cancelled 时 `cancel_pending()`（不新增 abort 钩子） |
| clear/restore：reset + reload project/session + 重建 overlay | `MemorySessionParticipant.on_new_session` / `on_restore_session` |
| close：`memory_coordinator.close()` 回收预取 | `resources=(AsyncCloseable)` |

理由：

- **TurnParticipant 够用但签名需扩展**：召回预取需要本 turn 用户消息；`before_turn()`
  原无参。turn 的用户消息是 generic turn 数据，不是 Memory 私有概念，协议保持窄。
  目前没有任何生产 TurnParticipant 实现（仅测试 fake），签名演进零迁移成本。
- **PromptLayer 表达不了注入语义**：`<relevant-memory>` 必须只进 Provider 投影的最后一条
  用户消息、不进系统提示、不进 canonical/JSONL（恢复测试断言
  `fake.received_messages[0][-1].text`）。系统提示 slot 与消息投影 slot 是两种贡献，
  混用会改变可观测行为。
- **abort 不值得开新钩子**：cancelled 状态在 after_turn（finally 内必然触发）可观察，
  用 turn 生命周期端点覆盖 abort 语义，SPI 不增 slot。

## 3. 新 primitive：`ProjectionLayer`

```python
class ProjectionLayer(Protocol):
    """对单次模型调用的 Provider 投影做非破坏性叠加，不触碰 canonical history。"""

    @property
    def layer_id(self) -> str: ...

    def project(
        self, messages: Sequence[AgentMessage], *, max_tokens: int | None
    ) -> list[AgentMessage]: ...
```

- `CapabilitySpec` 增加 `projection_layers: tuple[ProjectionLayer, ...] = ()`（构造期归一化
  为 tuple，与既有字段一致）；registry 增加聚合 property；`close_all` 无需变化。
- `CapabilityRuntime` 增加同步折叠分发：

```python
def project_context(
    self, messages: Sequence[AgentMessage], *, max_tokens: int | None
) -> list[AgentMessage]:
    projected = list(messages)
    for layer in self._registry.projection_layers:
        projected = layer.project(projected, max_tokens=max_tokens)
    return projected
```

- `CapabilityLifecycle` 协议增加 `project_context`（与 before/after_turn、session、close
  同为 coordinator 的能力分发端口）；空 registry 时折叠为恒等，Bare 图零开销、行为不变。
- 调用点：`AgentRuntimeCoordinator.prepare_core_context` 在
  `ContextManager.prepare` 之后调用 `self._capabilities.project_context(...)`，
  `max_tokens=state.effective_window_tokens`。coordinator 只认识端口，feature-blind。

为什么这是合法的 generic primitive：它与"哪个 Capability"无关——检索增强、上下文水印、
评测注入等任何"每次模型调用临时叠加、不可持久化"的 Feature 都是这个形状。相反，
Plan 的 clear-and-execute 是"会话状态机迁移"，不符合本 primitive，维持不恢复。

## 4. `chat()` 时序调整（唯一控制流改动）

```text
chat(user_message):
  execution.begin / last_stop_reason = None
  try:
    api_configured? ─否→ notice + return
    ensure_core_session_ready
    cancelled? → return
    compact_core_context_if_needed          ← 压缩可能替换 messages
    cancelled? → return
    await capabilities.before_turn(user_message)   ← 移动到此处（原在 try 头部）
    await runtime.prompt(user_message)
    sync_core_outcome / should_compact
  finally:
    await capabilities.after_turn()
```

- `before_turn` 从 try 头部移到压缩之后、`prompt` 之前。理由：Memory 参与者需要在
  **压缩后**的 transcript 上取 `turn_start_index = len(transcript.messages)`（压缩会收缩
  messages，先取索引会错位），这与 PR1 前编排点完全一致。目前无其他参与者受影响；
  spec 措辞"before the Provider stream starts"仍成立。
- 早退路径（api 未配置 / cancelled）不触发 before_turn：与 PR1 前一致（快照在检查之后）。
  `MemoryTurnParticipant` 以"本轮是否 begin 过"为守卫，after_turn 只在有 begin 的轮收尾。

## 5. Memory Capability 组装

### 5.1 `lion_code/capabilities/memory.py`（新文件，Capability 层）

- `MemoryTurnParticipant(coord, transcript)`：
  - `before_turn(user_message)`：记录 `turn_start_index = len(transcript.messages)` →
    `coord.begin_user_turn(user_message)`。
  - `after_turn()`：本轮已 begin 才执行：cancelled → `coord.cancel_pending()`；
    `await coord.finish_user_turn(user_message, turn_start_index)`；清除本轮标记。
- `MemorySessionParticipant(coord)`：两事件均调 `coord.reset_for_session()`。
- `MemoryProjectionLayer(coord)`：`layer_id="memory"`，`project` 委托
  `coord.project(messages, max_tokens=...)`。
- `MemoryResource(coord)`：`close()` → `await coord.close()`。
- `create_memory_capability(coordinator) -> CapabilitySpec`：name=`"memory"`，装配上述四类。
  工厂只做绑定，SessionMemoryCoordinator 仍由 Composition Root 构造（与 plan/skill/subagent
  模式一致），`AgentComposition.session_memory_coordinator` 字段保留供 Full facade 命令面使用。

### 5.2 `SessionMemoryCoordinator` 公有化窄方法（私有编排 → capability 契约）

| 新公有方法 | 包装的现有私有逻辑 |
|---|---|
| `begin_user_turn(user_message)` | `_prepare_turn_memory_snapshot`（含 is_sub_agent 内部 gating） |
| `finish_user_turn(user_message, start_index)` | `_update_session_memory_after_turn`（is_sub_agent gating 移入）+ `_build_turn_memory_overlays` 刷新 |
| `project(messages, *, max_tokens)` | injector.inject + 记录 `last_memory_injection` |
| `reset_for_session()` | `memory_coordinator.reset` + `_reload_project_memory` + `_reload_session_memory` + 报告重置 + overlay 重建 |

私有方法就地删除或改为公有实现体，不留兼容别名。`set_query_service` 已无调用者，删除。

### 5.3 Narrow model query（PR2/PR6 遗留闭环）

`ProviderTextQueryService.__init__` 的 `provider` 参数改为
`ModelProvider | Callable[[], ModelProvider]`，`complete()` 调用时解析。组合根传
`lambda: runtime_coordinator.core_runtime.provider`（live 访问器，热替换自动生效）。
ProviderManager 不感知 Memory，无 sink、无通知，不复活 `MemoryQuerySink`。

### 5.4 组合根接线（`_build_session_graph`）

`_CAP_MEMORY` 选中时：构造 `SessionMemoryCoordinator`（query 改传 live provider 访问器）→
`capability_registry.register(create_memory_capability(coord))`。晚于
`_install_capability_tools` 注册无害：Memory 无 ToolSource，prompt layers 经
`lambda: registry.prompt_layers` 惰性读取，projection 同理惰性聚合。

## 6. 其余 Capability 复核结论

- **Skill**：`skill` 工具描述 + 动态上下文已承载使用说明；无 PromptLayer 需求。零改动。
- **Plan**：三 slot 正确。`PlanPromptLayer.render` 每次实时投影 PlanView，无状态镜像；
  clear-and-execute 维持 PR3 删除状态（Kernel 无 Plan 认知，无 generic primitive 需求）。零改动。
- **SubAgent**：`SubagentFactory._create` 已延迟导入 `build_coding_agent`（唯一构造入口）
  → `CodingProfile` → `build_agent_composition`，与主 Agent 共享 Kernel/Harness。
  补架构断言：`subagent_factory.py` 只允许经 `meta_agent` 构造 child（禁止 import
  `agent`/自建 runtime）。零生产改动。
- **MCP**：PR7b 已删（`McpManager`/`ToolEnvironment` 不存在）。验收点 6 的实现是
  "保持不存在 + spec 记录契约"：未来外部工具 Capability 必须自持连接、经
  resources/AsyncCloseable 关闭，generic 层不得出现协议客户端。零改动。

## 7. 门禁同步

- `tests/architecture/test_bare_composition.py`：
  `_FEATURE_MODULE_PREFIXES` += `lion_code.capabilities.memory`；
  `_FEATURE_SYMBOLS` += `MemoryProjectionLayer`、`MemoryTurnParticipant`、
  `MemorySessionParticipant`、`create_memory_capability`。
- `tests/capabilities/test_capability_registry.py`：fake participant 签名同步
  `before_turn(user_message)`；补 projection_layers 聚合/折叠/空注册表恒等测试。
- `tests/memory_runtime/test_core_integration.py`：解除 7 个 `_REHOME` skip；
  monkeypatch 目标从 facade 私有 seam 改到 coordinator（`_extract_session_memory_semantics`
  等 facade 委托已不存在，测试直接 patch coordinator 方法或注入 fake query）。
- import-linter / `_boundaries.py`：capabilities 禁止集合仍为 `{agent, agent_runtime}`，
  无需变化（`capabilities.memory` → `session_memory_coordinator`/`memory_runtime` 是
  Capability→Capability/Kernel 依赖，合法）。

## 8. Tradeoffs

- **同步 `project` 而非 async**：注入是纯内存变换（copy-on-write 投影），无 IO；
  async 化会让所有参与者付出 await 成本且无真实需求。
- **turn_start_index 由参与者自记**而非经协议传参：索引只在 begin/finish 间有意义，
  是 Memory 的私有簿记；协议只传 generic 的 user_message。
- **provider 惰性解析而非事件刷新**：避免恢复 ProviderManager→Memory 通知链；
  读取时解析天然正确，代价是每次 side query 一次属性访问。
- **不引入 CapabilityContext**：参与者按需持有各自窄依赖（TranscriptView、
  CancellationView、coordinator），不经共享 god-object。

## 9. Rollout / Rollback

- 单 PR：SPI 扩展（types/registry/runtime）→ memory capability → 组合根接线 →
  chat 时序调整 → 测试恢复/新增 → 门禁与 spec 同步。每步可独立 `py_compile` +
  定向 unittest 验证。
- 回滚点：整个 PR revert 即回到 PR7c 状态；无数据迁移、无持久化格式变化
  （Session Memory JSON 结构不变）。
