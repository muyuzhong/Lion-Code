# Ephemeral Agent State Context

## Goal

在每次 Provider 调用前向 prepared context 尾部追加一条临时的 Agent 状态快照，帮助模型理解当前运行态，同时保持 canonical conversation history、JSONL Session 和 Compaction 输入不变。

## Confirmed repository facts

- `CapabilitySpec` 当前在 `lion_code/capabilities/types.py:74-110` 以 frozen/slots value object 表达四个扩展槽；`CapabilityRegistry` 在 `lion_code/capabilities/registry.py:39-119` 聚合槽位且不是 service locator。
- `ContextManager.prepare()` 在 `lion_code/context/manager.py:39-63` 先深拷贝并执行 budget/snipping/clearing/compaction projection；`ContextRuntime.prepare_context()` 在 `lion_code/runtime/context.py:107-112` 将结果交给 Core Provider hook。
- `run_agent_loop()` 在 `lion_code/core/loop.py:139-146` 对 Provider context 调用 `prepare_context`，canonical `messages` 只在后续 Core 事件中追加 assistant/tool-result 消息；因此 prepared-only 消息可以保持瞬态。
- `PromptComposer.get_system()` 在 `lion_code/prompt.py:54-64` 每轮重新渲染 PromptLayer；`build_dynamic_system_context()` 的 OS/Shell/Git 环境动态 section 在 `lion_code/prompt.py:303-337`，本 PR 不把运行态状态栏混入该 system prompt。
- Composition Root 在 `lion_code/composition/agent_builder.py:230-372` 汇合 Profile/Config/Bindings；`_build_capability_graph()` 在 `:573-618` 注册内置及 extension specs；`_build_tooling_graph()` 在 `:642-698` 创建 PromptComposer 和 ContextManager。
- reachable-object-graph 辅助函数在 `tests/architecture/test_runtime_ownership.py:191-277`，当前门禁在 `:312-338` 检查 AgentRuntime、SessionRuntime、CapabilityRuntime、SubagentFactory 不可达 ProviderController；ContextRuntime compaction state 的唯一 owner 门禁在 `:493-523`。

## Requirements

### R1. ContextLayer SPI

- 在 `capabilities/types.py` 增加 `ContextLayer` Protocol：`layer_id` 与 `render(view: ContextView) -> str`。
- docstring 明确语义：PromptLayer 贡献相对稳定的 System Prompt，ContextLayer 贡献每轮刷新、仅存在于 prepared context 的当前状态。
- `CapabilitySpec` 增加 `context_layer: ContextLayer | None = None`，保留现有调用方的默认行为；Registry 提供已注册 ContextLayer 的只读聚合。

### R2. Read-only ContextView

- 在 `context/types.py` 定义 frozen/slots 的只读视图及最小数据结构，包含当前时间、最近 Provider 调用 token 用量/上限/百分比/compaction 状态、从消息序列推导的工具调用参数摘要轨迹、最近最多三个失败 ToolResult 的单行摘要。
- 视图构造只使用局部不可变值和 tuple，不新增 mutable state owner，不复制 traceback，不修改输入消息。

### R3. Prepared-context 状态注入

- `ContextManager.prepare()` 保留现有 budget/snipping/clearing/protected-window 流程，在最后一步按 `layer_id` 稳定排序并 render 所有已注册 ContextLayer。
- 非空 layer 输出拼接为一条临时 `role=user` 消息，内容由 `<agent-state>...</agent-state>` 包裹，追加到本次 prepared context 尾部。
- 未注册 ContextLayer 时，Minimal Profile 的 prepared context 与改动前逐 token 一致；状态消息不进入 canonical Harness history、JSONL Session、CompactionEntry 或 compactor 输入。

### R4. Built-in projections

- AgentStateLayer 只读取 ContextView，渲染 Time、Context、Activity、Recent failures；Activity 对相同工具/参数摘要优先显示重复次数。
- Plan Capability 通过自己的 ContextLayer 提供 Task 行，AgentStateLayer 不感知 Plan。
- GitStatusLayer 独立计算当前 cwd、branch、dirty files；OS/Shell/Architecture 静态信息继续由现有 system-prompt dynamic section 提供。
- Built-in layer 通过 CapabilitySpec/ContextLayer 接线，Feature-specific construction 留在 Composition/Capability 包，不进入 Kernel 或 Runtime。

### R5. Tests and quality

- 增加 SPI/聚合、ContextView 统计与失败摘要、稳定排序和格式渲染测试。
- 增加瞬态性测试，覆盖 canonical history、JSONL、CompactionEntry 及 compactor 输入；增加无 ContextLayer 零回归和 Capability 移除后 MetaAgent/AgentRuntime 独立性测试。
- 延续 reachable-object-graph 门禁，证明带 ContextLayer 的 Profile 不引入新的 mutable owner，且不违反 Runtime/Kernel 依赖边界。
- 按仓库现有质量约定运行 compileall、ruff、mypy、import-linter、coverage/测试门禁；区分本次变更结果与既有 dirty-worktree/baseline 噪声。

## Constraints and out of scope

- 禁止修改 `core/runtime/agent.py`、`runtime/conversation.py`、`runtime/session.py`、`runtime/provider.py`、`meta_agent.py`；`runtime/context.py` 仅在现有 hook 不足时做最小改动，优先保持零改动。
- 不给历史消息逐条增加 timestamp；时间只出现在状态栏。
- ContextRuntime/ContextManager 不硬编码 Plan、Todo 或其他具体 Feature 状态；不新增工具计数、失败记录等 mutable owner，全部从既有 AssistantMessage/ToolResultMessage 推导。
- 不引入新的持久化格式、history message 类型、compactor 输入通道、fallback/兼容层或预防性抽象。

## Acceptance Criteria

- [x] `ContextLayer` Protocol、`CapabilitySpec.context_layer` 和 Registry 聚合可被旧四槽 Capability 无改动使用。
- [x] 每次有 ContextLayer 的 Provider 请求尾部恰好追加一条 `<agent-state>` UserMessage；无 layer 时 prepared message/token 序列不变。
- [x] ContextView 对给定 tool_calls 和失败 ToolResult 产生正确的参数摘要、重复 Activity 和最多三个单行 failure。
- [x] 状态消息不出现在 canonical `AgentMessage` history、JSONL session、`CompactionEntry` 或 compactor 接收到的消息中。
- [x] AgentState、Plan、Git status layer 的职责和排序符合设计，Git status 每次 render 读取当前工作区。
- [x] 带 ContextLayer 的 Profile 通过 runtime ownership reachable-graph 门禁，无新的 mutable owner 或 Runtime 对具体 Feature 的依赖。
- [x] 移除/不注册新增 capability 后，MetaAgent、AgentRuntime 和已有 Minimal/Coding/Full 基础能力仍可独立组合。
- [x] 所有变更通过聚焦测试、全量测试和适用质量门禁，且仅提交本任务范围内的文件。

## Scope decision

- Built-in AgentState/GitStatus are scoped to non-Minimal product compositions; explicit `extension_specs` remain available to every Profile, including Minimal.
