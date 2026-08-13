# 接入 Capability PromptLayer 与 SessionParticipant 运行时

## Goal

基于完成 Domain dependency narrowing 后的 `master`（当前基线
`3e5dfb3`），让已有 Capability SPI 的 `PromptLayer` 与
`SessionParticipant` 真正驱动运行时，以 Plan 作为完整验证案例。Plan
Capability 最终同时贡献 ToolSource、PromptLayer 和 SessionParticipant；运行时
不再把 Plan prompt 复制到 Agent 或 PlanRuntime 的可变字段中。

本任务不做 AgentBuilder，不引入通用 Service Locator、兼容层、migration 或
fallback。工作树中已有的非本任务修改必须保留，提交时只包含本任务文件。

## Confirmed Facts

- `lion_code/capabilities/types.py:46-88` 已定义 PromptLayer、TurnParticipant、
  SessionParticipant 和 AsyncCloseable；`CapabilitySpec` 与 Registry 已能聚合
  各 slot（`types.py:96-141`、`registry.py:191-259`）。
- `lion_code/capabilities/plan.py:18-41` 当前只有绑定 PlanRuntime 的
  enter/exit ToolSource。
- `lion_code/plan_runtime.py:26-30,81-229` 当前仍通过 host 的
  `_base_system_prompt`、`_system_prompt` 和 `refresh_prompt()` 同步 prompt。
- `lion_code/agent.py:411-427,571-615,1058-1071,1128-1139,1393-1395` 当前由
  Agent 持有 prompt 镜像，并转发 turn/close Capability hooks。
- `lion_code/agent_runtime.py:240-268,317-374,670-697,762-809` 当前通过
  Agent-shaped host 读取 prompt、Plan reset 和 Capability hooks。
- `lion_code/session_lifecycle.py:48-135` 当前直接调用
  `session.plan.reset_for_new_session()`、`reset_after_restore()` 和
  `identity._close_capabilities()`。
- `lion_code/prompt.py:244-290` 已有 static prompt 与 dynamic context builder；
  Core 每轮通过 `get_system` 重新读取 system prompt（`core/loop.py:132-155`）。

## Requirements

### R1. PromptComposer

- 新增独立 `PromptComposer`，职责只包括组合：稳定 base prompt、dynamic
  system/project/tool context、Capability PromptLayers。
- 组合顺序固定为 `stable base -> dynamic tail -> non-empty layer fragments`，
  保持现有 static-prefix + dynamic-tail 的 cache-friendly 顺序。
- `get_system()` 每次调用都重新读取当前 Registry layers，并按 Registry 的依赖
  解析顺序渲染；不缓存 Plan layer 的渲染结果。
- Composer 不知道 Plan、MCP、Memory 等具体 Capability，也不包含 canonical
  conversation history。
- 保持 `custom_system_prompt` 现有语义：传入 truthy custom prompt 时替代默认
  static/dynamic prompt；Capability layers 仍可追加。

### R2. Plan prompt projection

- 新增 `PlanPromptLayer`，只依赖 `PlanView`。
- inactive 渲染为空字符串；active 渲染现有 Plan instructions，并包含当前 plan
  file path。
- `render()` 只读 PlanView，不修改 PlanRuntime、PlanState、Permission 或 host。
- PlanRuntime 删除 `_base_system_prompt`、`_system_prompt`、host prompt mutation
  和 `refresh_prompt()`；Plan prompt 是 PlanState 的实时 projection。
- PlanRuntime 只保留 PlanState、permission transaction、approval、plan path 和
  pending context reset 的责任。

### R3. Plan SessionParticipant

- 新增 `PlanSessionParticipant`，实现 `on_new_session` 与
  `on_restore_session`，分别调用 PlanRuntime 的对应 session transition。
- 新 session 在 identity transition 之后调用 capability participant；restore
  在 canonical messages/config 恢复和 identity transition 之后调用 participant。
- `SessionLifecycle` 删除所有 Plan-specific reset 调用，不引用 PlanRuntime、
  `.plan` 或 Plan prompt 细节。

### R4. Generic capability lifecycle

- 新增极薄 `CapabilityRuntime`/`CapabilityLifecycleAdapter`，只持有
  CapabilityRegistry，并提供：`before_turn`、`after_turn`、`on_new_session`、
  `on_restore_session`、`close`。
- 不提供 `get_service`、`get_capability` 或其他 dependency lookup，不持有
  kernel state。
- Agent 删除 generic capability hook forwarding；AgentRuntimeCoordinator 与
  SessionLifecycle 只依赖 generic lifecycle port，不依赖 Agent hook methods。
- close 对 Capability resources 至多执行一次；Registry 既有依赖逆序、错误继续
  尝试和首个错误重抛语义保持不变。ToolEnvironment/MCP ownership 不迁移。

### R5. PlanCapability 与工具绑定

- 在现有唯一 `create_plan_capability(runtime)` 上扩展，不创建第二个 Plan
  Capability。
- PlanCapability 贡献一个 ToolSource、一个 PlanPromptLayer、一个
  PlanSessionParticipant。
- enter/exit tools 继续在构造时直接绑定 PlanRuntime，保持 approval choices、
  `ToolResult.terminate`、clear-and-execute 和 pending context reset 语义。
- 不重新通过 Agent 路由 Plan tools。

### R6. Lifecycle ordering

必须通过测试锁定以下顺序：

- new session：session identity transition -> capability `on_new_session` -> core
  session ready -> first provider request 读取 fresh PromptComposer。
- restore：restore canonical messages/config -> restore session identity -> capability
  `on_restore_session` -> first next request 读取 fresh prompt。
- turn：capability `before_turn` -> core run -> capability `after_turn`，包括 early
  API exit、取消、tool/provider failure。
- close：Capability resources 只关闭一次；既有 MCP/ToolEnvironment ownership 保持。

### R7. 完整 SPI 测试 Capability

增加测试专用 Capability，同时贡献 ToolSource、PromptLayer、TurnParticipant、
SessionParticipant 和 AsyncCloseable resource，覆盖 slot 安装/读取和上述 runtime
lifecycle 顺序；测试不得依赖真实 Provider API。

### R8. Architecture tests and behavior preservation

增加或更新架构测试，至少验证：

- PlanRuntime 不引用 `_system_prompt` / `_base_system_prompt`。
- SessionLifecycle 不引用 PlanRuntime、`.plan` 或 Plan prompt symbols。
- Agent 不包含 generic capability hook forwarding。
- PromptComposer 不 import concrete Capability。
- PromptLayer render 不写 runtime state。
- SessionParticipant 保持单一 session transition 责任，不成为 god interface。

保留现有 Plan permission semantics、approval choices、clear-and-execute、pending
context reset、plan path、prompt cache ordering、MCP lifecycle 和 tool behavior。

## Acceptance Criteria

- [ ] `PromptComposer.get_system()` 输出顺序正确，每次读取最新 layers，且不包含
      canonical history。
- [ ] custom prompt、Plan inactive/active/path projection 和 static-prefix /
      dynamic-tail cache ordering 均有测试。
- [ ] PlanRuntime 已删除 prompt mirror、host prompt mutation 和 refresh_prompt；
      PlanState 仍只有一个 writer。
- [ ] PlanCapability 的唯一 spec 同时提供 ToolSource、PromptLayer、
      SessionParticipant；Plan tools 仍直接绑定 PlanRuntime。
- [ ] SessionLifecycle 不含 Plan knowledge；new/restore/turn/close 顺序测试通过。
- [ ] Agent 不再实现 generic capability hook forwarding；generic adapter 的
      close idempotency 和 Registry ordering 有测试。
- [ ] 测试 Capability 覆盖全部 SPI slots，并验证 lifecycle 事件顺序。
- [ ] 原有 Plan、MCP、Tool、permission、approval、context reset、session restore
      行为测试保持通过。
- [ ] `python -m pytest -q`、`python -m compileall -q lion_code tests`、
      `lint-imports --no-cache`、架构测试、`git diff --check` 和 Trellis task
      validation 全部通过；与本任务无关的既有 dirty 文件不被提交。

## Out of Scope

- AgentBuilder 或通用依赖注入 / Service Locator。
- Memory Host、Provider ownership、ToolEnvironment/MCP ownership 的重新设计。
- 新的用户可见 Plan 语义、持久化格式、migration、兼容层或 fallback。
- 与 PromptLayer / SessionParticipant 接入无关的能力迁移或架构阶段。

## Open Questions

无。当前代码、SPI spec 和用户要求已经确定实现边界；技术取舍记录在
`design.md`。
