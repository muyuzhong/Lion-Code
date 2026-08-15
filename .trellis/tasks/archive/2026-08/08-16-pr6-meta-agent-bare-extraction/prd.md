# PR6 MetaAgent Bare Extraction

## Goal

建立一个真正的 `MetaAgent`：`Agent Kernel + Harness Runtime + empty CapabilityRegistry` 是完整、可运行的产品状态，并且允许 `tools=[]`。它不是 Bare Coding Agent，也不通过 Null/Noop/Deferred Feature 替身伪造完整对象图。

## Confirmed Repository State

- 2026-08-16 已执行 `git fetch origin --prune`；本地 `master` 与 `origin/master` 均为 `58564ce`。
- PR0 #28、PR1 #29、PR3 #30、PR4 #31、PR5 #32 均已合并。PR1 先合入 PR0 分支，随后随 PR0 进入 `master`。
- 没有独立 PR2。PR1 归档明确把 `ProviderManager -> MemoryQuerySink` 留给 PR2；当前 `provider_manager.py` 与 composition 仍存在该依赖和 `DeferredMemoryQuerySink`，因此 PR2 的 bare-path 解耦事实尚未完成。
- PR5 已使 `build_agent_composition(..., capabilities=frozenset())` 不创建八类高级 Feature，但默认 bare 路径仍会创建 Feature-specific construction helpers，并且没有独立、无 Feature API 的 facade。
- Kernel 已声明并真实发射 turn/model/tool/cancellation 事件；compaction 类型已经进入 `AgentEvent`，但运行时尚未真实发射。

## Requirements

### R1. Zero-extension and zero-tool are valid runtime states

- 新增 `build_meta_agent(provider=fake_provider, tools=[])` 公共入口。
- 构建结果使用空 `CapabilityRegistry`，不注册内置 Capability。
- `tools=[]` 时 Provider 收到空工具列表，`await agent.run("hello")` 完成 `user -> provider -> assistant`。
- 默认 Meta prompt 与 compaction prompt 不包含 Coding 或高级 Feature 指令。

### R2. MetaAgent exposes only generic facade capabilities

允许公开：run/chat/prompt、conversation/messages、subscribe、steer/follow_up/continue、cancel、compact、session id/new/restore、provider/model/thinking 配置、usage/budget、close。

禁止公开名称或委托：dream、memory、plan、goal、autonomous loop、learning、subagent、skill、mcp。MetaAgent 不保留 `AgentComposition` 或 Feature 字段作为 facade 状态。

### R3. Bare object graph contains no advanced Feature object or substitute

- Bare 构建不得调用 Memory、Plan、MCP、Skill、SubAgent、Autonomy、Dream、Learning 的构造函数或 capability factory。
- 删除未完成 PR2 遗留的 `ProviderManager -> MemoryQuerySink` 依赖、adapter 与 deferred sink。
- 仅在对应 capability 被选择时创建 Feature-specific status/notice/resource helpers；MetaAgent 路径不得为它们创建占位对象。
- 不新增 NullFeature、NoopFeature、fallback Feature、ServiceLocator、Profile 系统或第二套 loop/runtime/session。

### R4. Event Stream is the Kernel outward contract

- 保持现有 `AgentEvent` / provider event 类型与 wire discriminator。
- 通过现有订阅入口真实暴露 turn start/end/fail、model lifecycle、tool lifecycle、cancellation。
- 在实际 compaction 周围真实发射 `CompactionStartedEvent` / `CompactionCompletedEvent`，区分 threshold/manual/overflow，并在取消时标记 `aborted=True`。
- 只补最小 publish 能力，不引入 Event Bus、队列或新的观察器框架。

### R5. Coding harness remains an explicit composition

- MetaAgent builder 只注册调用方传入的 `LionTool`，不得 import 或自动创建 builtin/internal coding tools。
- 单独的集成测试显式传入 filesystem/search/edit/shell 工具与 coding permission，证明 `model -> tool call -> tool result -> provider -> final response`。
- Coding tools 与 coding policy 不得成为 Kernel contract。

### R6. Session, compaction, cancellation, usage and close remain generic

- MetaAgent 复用 canonical messages、ContextManager/Compactor、ExecutionControl、UsageLedger/BudgetPolicy、SessionRepository/Recorder 与 ProviderManager。
- session 自动保存，new session 与 restore 可恢复 canonical conversation。
- cancel 可终止运行并由事件流观察；close 幂等收敛 Provider、空 capability runtime 与可选资源。

### R7. Full Product degradation is explicit and not re-homed here

移除 ProviderManager 的 Memory query refresh 后，不在本 PR 通过新 hook、observer 或 capability adapter 恢复 Memory 的 provider replacement 行为。该行为进入下一阶段 Feature Re-home；本 PR 只完成 bare ownership 删除并保持其他 Provider/runtime/session 不变量。

## Acceptance Criteria

- [ ] A. `build_meta_agent(provider=fake_provider, tools=[])` 可完成纯文本 smoke test，Provider 只看到空工具列表。
- [ ] B. 显式传入 coding tools 后，真实完成一次 tool-call loop；测试证明 coding tools 来自调用方而非 Kernel/MetaAgent 默认值。
- [ ] C. 空 CapabilityRegistry 是 facade 内部真实状态；没有高级 Feature 实例、placeholder 或 facade API。
- [ ] D. monkeypatch 所有高级 Feature 构造函数/factory 为 `AssertionError` 后，build、provider call、tool loop、compact、session save/restore、cancellation、close 全流程通过。
- [ ] E. 订阅者能观察真实 turn/model/tool/compaction/cancel 生命周期；compaction 事件来自 runtime 执行点。
- [ ] F. 架构门禁只扫描 Kernel、generic Harness 与 MetaAgent 路径，拒绝八类高级 Feature concrete reference，不误伤 Product/Capability 模块。
- [ ] G. ProviderManager 不再 import Memory，也不接受/持有 Memory sink；既有 provider/runtime/context/recorder 原子更新测试继续通过。
- [ ] H. 全量 pytest、compileall、import-linter 与仓库既有质量基线通过；无新增依赖。
- [ ] I. `.trellis/spec/backend/four-layer-ownership.md` 与 `tests/OWNERSHIP.md` 对 PR2/PR6/Event Stream 的描述和真实实现一致。
- [ ] J. 只提交 PR6 相关文件，中文提交描述；保留当前工作树中已有 Trellis/Claude/Codex 改动。

## Out of Scope

- Memory/Plan/MCP/Skill/SubAgent/Autonomy/Dream/Learning 的重新接线或功能恢复。
- Profile 系统、Feature flag 框架、复杂 Event Bus、Supervisor 实现。
- 重写 Provider adapter、Agent Loop、ToolRuntime、SessionRepository 或 execution backend。
- 保留旧 Feature 行为的兼容层、migration、fallback。

## Technical Notes

- `build_agent_composition` 继续承担 Full Product composition；MetaAgent 复用其 generic construction stages，但只保留通用 facade 状态。
- 直接注入 `ModelProvider` 是 Harness dependency，不通过伪造 API key 绕过 `api_configured`。
- Full Product 的 Memory provider-refresh 回归不在 PR6 伪装修复，按 Feature Re-home 明确延期。
