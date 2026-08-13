# Design: Capability PromptLayer 与 SessionParticipant 运行时接入

## Boundary

本任务把 Capability 的声明 slot 接到已有 Agent composition/runtime seam，保持
Kernel state 的所有权不变：

```text
Agent composition root
  -> CapabilityRegistry
       -> PromptComposer.get_system() -> LionAgentRuntime -> Provider
       -> CapabilityRuntime -> AgentRuntimeCoordinator / SessionLifecycle

PlanState <- PlanRuntime <- PlanPromptLayer (PlanView projection)
                     \- PlanSessionParticipant (session transition adapter)
                     \- Plan ToolSource (direct PlanRuntime binding)
```

`CapabilityRuntime` 是 lifecycle port 的唯一 generic adapter。它只保存 Registry
引用；每次 dispatch 都从 Registry 的聚合 slot 读取当前 participants，不能提供
任何 capability/service lookup，也不复制 kernel state。

## Prompt composition

在现有 `lion_code.prompt` 中加入独立 `PromptComposer`，不让它导入任何具体
Capability。Composer 接受稳定 base、dynamic context 和一个 layer provider：

```python
PromptComposer(
    stable_base_prompt=...,
    dynamic_context=...,
    layers=lambda: capability_registry.prompt_layers,
)
```

`get_system()` 每次按如下顺序构造新字符串：

1. stable base prompt；
2. 当前 dynamic system/project/tool context（若非空）；
3. 对 provider 当前返回的每个 layer 调用 `render()`，过滤空 fragment。

Composer 允许 composition root 在 Dream 后替换 dynamic context，但不存储 Plan
prompt；Plan layer 的 fragment 始终由 `render()` 从 PlanView 即时读取。这样既保留
static prefix + dynamic tail 的 cache 边界，也避免把 canonical messages 或 Plan
prompt 镜像放进 Agent/PlanRuntime。

`custom_system_prompt` 仍走原来的 truthy 分支：custom prompt 作为 stable base，
默认 dynamic context 为空；Capability layers 仍由 Composer 追加。

## Plan capability

`PlanRuntimeHost` 缩减为 session identity 与 notice 所需的窄依赖，删除两个 prompt
字段。PlanRuntime 的 `initialize`、`_enter`、`_leave`、new/restore reset 只写
PlanState 或执行 PermissionController transaction，不再触发 prompt refresh。

`PlanPromptLayer` 接受 `PlanView`，`layer_id` 固定为 `plan`。inactive 返回空；active
复用既有 Plan instructions 文本，并把 `file_path` 读入文本。其 `render()` 没有
写操作，因此每次 Core 的 `get_system()` 调用都能看到当前 PlanState。

`PlanSessionParticipant` 只保存 PlanRuntime，并把两个 SPI 回调一一映射到
`reset_for_new_session()` / `reset_after_restore()`。它不拥有新的 PlanState，也不
把 session lifecycle 扩展成新的 god interface。

`create_plan_capability` 仍是唯一 Plan Capability factory，返回同一 runtime 绑定的
ToolSource、PromptLayer 和 SessionParticipant。Tool command 的闭包继续直接调用
`runtime.enter()` / `runtime.exit()`，保留 `terminate` 投影。

## Lifecycle adapter and ports

新增 `CapabilityLifecycle` protocol 与 `CapabilityRuntime` 实现，方法为：

```python
before_turn()
after_turn()
on_new_session()
on_restore_session()
close()
```

方法分别按 Registry dependency-resolved 顺序遍历对应 participant；`close()` 调用
Registry 的既有 reverse-dependency `close_all()`，并用一次性 guard 确保重复
`Agent.close()` 不会再次 close Capability resources。错误继续/首错重抛仍由 Registry
负责。

`AgentRuntimeCoordinator` 接收 generic lifecycle port，`chat()` 在 Core run 外层
调用 before/finally-after。`SessionLifecycle` 也接收同一 port：new/restore 在 identity
transition 后调用对应 participant，close 调用 port.close。Agent 不再提供
`_before_turn_capabilities`、`_after_turn_capabilities` 或 `_close_capabilities`。

Coordinator 仍可通过既有 `SessionStateHost` 读取 PlanView 来完成 pending context
reset；这不是 SessionLifecycle 的 Plan knowledge，也不改变 PlanState 单 writer。

## Session ordering

### New session

1. flush background operations and reset project/session memory runtime；
2. reset `SessionIdentityState`；
3. call `CapabilityRuntime.on_new_session()`；Plan participant generates the new
   path and clears pending reset；
4. clear Core queues/messages, reset observers and await core session readiness；
5. reset usage/overlays and emit the existing notice；the next provider request calls
   `PromptComposer.get_system()` and sees the new Plan projection.

### Restore

1. load canonical session state and restore provider model/thinking configuration；
2. clear/replace Core messages with persisted canonical messages；
3. reset session identity from restored session metadata；
4. call `CapabilityRuntime.on_restore_session()` to clear pending Plan reset without
   changing restored Plan path；
5. reset observers, await core readiness, reset usage/overlays and emit notice；the next
   request obtains a fresh prompt projection.

### Turn / close

`before_turn -> core readiness/compaction/prompt/tool loop -> after_turn` remains wrapped
by `finally`, including API-not-configured and failure paths. Close retains the existing
Memory -> Core Provider -> Capability resources -> ToolEnvironment/MCP order; only the
Capability dispatch owner changes.

## Compatibility and rollback

- No compatibility aliases for removed Agent hooks or Plan prompt fields.
- Existing Plan approval choices, permission restoration, context-reset persistence and
  tool result termination remain in PlanRuntime and its current tests.
- Existing MCP discovery remains a TurnParticipant and MCP process shutdown remains
  ToolEnvironment-owned; CapabilityRuntime.close never calls MCP manager shutdown.
- Roll back in slices: PromptComposer/Plan projection, then lifecycle wiring, then test and
  spec updates. No persistence schema or external resource ownership changes.

## Risks and mitigations

- Prompt ordering drift: unit test exact section order and custom prompt semantics.
- Stale Plan text: test one Composer instance across PlanState transitions and assert
  successive `get_system()` calls differ without calling a refresh method.
- Session callback order drift: use one test Capability with event log plus fake Core/
  Provider integration for new/restore/turn/close.
- Double close: call close twice and assert resource count is one; separately retain MCP
  ToolEnvironment ownership assertion.
- Hidden Agent forwarding: AST tests inspect Agent, SessionLifecycle, PlanRuntime and
  PromptComposer for forbidden symbols/imports and mutation patterns.
