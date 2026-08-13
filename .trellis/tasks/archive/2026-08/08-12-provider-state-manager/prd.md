# 重构 Provider 配置与 Thinking 生命周期所有权

## Goal

在完成 PR1 的 `master` 基线之上，把 Provider/model/credential/thinking 的可变源状态
集中到 `ProviderManager`，让 `Agent` 只保留兼容 facade 和组合根职责。这样 Provider
切换、Thinking 热替换与 Session restore 都通过明确命令完成，同时保留一个活跃 Provider、
一个 Core Runtime 和一份 canonical conversation history。

## Confirmed Facts

- `lion_code/agent_lifecycle.py:27-63` 当前的 `AgentLifecycleHost` 直接暴露配置字段、
  Core Runtime、Context compactor、Memory coordinator、Session recorder 和缓存；其
  `configure_api()` / Thinking 方法在 `agent_lifecycle.py:83-316` 直接写这些宿主属性。
- `Agent.__init__()` 在 `lion_code/agent.py:162-208` 保存 `model`、`use_openai`、
  `thinking`、凭证/base URL 和 Thinking 私有字段；`agent.py:311-328` 再把这些字段
  组装进 Core Runtime。
- `SessionLifecycle.restore_core_session()` 在 `lion_code/session_lifecycle.py:98-108`
  当前直接写 `identity.model`、模型限制缓存和 Thinking 私有入口。
- `LionAgentRuntime.replace_provider()` 原位更新同一个 Harness 的 Provider，消息历史
  保持在该 Runtime；当前测试已经覆盖 hot model swap、协议切换、失败回滚、compactor /
  Memory query refresh、旧 Provider 异步关闭和 `lion_code.agent.create_provider` patch
  seam（`tests/integration/test_agent_core_runtime.py:856-1110`）。
- `Agent._create_provider()` 在 `lion_code/agent.py:804-806` 调用本模块的动态
  `create_provider` 名称；该调用路径必须继续作为 factory/monkeypatch 兼容锚点。

## Requirements

- R1：新增可变 `ProviderState`，权威字段只有 `model`、Provider/backend kind、api key、
  OpenAI base URL、Anthropic base URL、Thinking enabled 和 Thinking level；不把
  `use_openai`、`provider_name`、`thinking_mode`、effective window 或 model-limit cache
  作为 State 的重复字段。
- R2：新增冻结的只读 `ProviderView`。需要 model/backend/thinking 的 Agent Runtime、
  UI/application 或 Session 逻辑消费 View；不得取得可写 State。
- R3：用 `ProviderManager` 替代 `AgentLifecycle(self)`。Manager 是配置与 Thinking 命令
  的唯一 Owner，提供 `configure`、`set_thinking`、`set_thinking_level`、
  `cycle_thinking_level`、`restore_configuration` 和 `build_provider`。
- R4：Manager 构造函数不接收 `Agent`，只依赖窄的 `ProviderRuntimePort`、
  `ModelContextControl`、`MemoryQuerySink`、`ConfigurationRecorder` 及必要的小型
  factory/scheduler Callable；移除 `AgentLifecycleHost`。
- R5：Provider 切换具备事务语义：先解析/验证目标并构建 replacement Provider 及派生
  服务；失败时旧 Provider、ProviderState、Core history、compactor、Memory query 和
  recorder 状态均不变；成功后依次替换 Runtime、提交 State、刷新 Context/Memory、记录
  变化，最后异步关闭旧 Provider。
- R6：保持单实例运行时语义、hot model swap、协议切换、history preservation、compactor
  refresh、model-limit invalidation、Memory query refresh、旧 Provider async close 和
  Thinking persistence。
- R7：保留 `lion_code.agent.create_provider` 的动态 factory/monkeypatch seam；既有
  factory tests、FakeProvider tests 和子 Agent 当前凭证继承行为继续成立。
- R8：Session restore 通过 ProviderManager 的明确 restore/apply command 恢复 model 和
  Thinking，不再直接赋值 `identity.model` 或 Thinking private field，也不为已存在的
  Session entry 重复写配置记录。
- R9：Agent 对外继续提供 `model`、`provider_name`、`api_configured`、provider
  config/get/configure、Thinking level、set/cycle Thinking；这些接口全部 delegate 到
  Manager/View。删除迁移后无用的 Agent Provider mutable mirrors 和 remote private-field
  mutations。
- R10：增加架构测试，锁定 Manager 不 import Agent、构造函数不接收 Agent、ProviderState
  只有 Manager 一个 writable owner、Agent 没有 ProviderState 字段的可变 mirror、以及
  Session restore 不直接写 Provider 私有字段。

## Acceptance Criteria

- [ ] AC1：`ProviderState` / `ProviderView` / `ProviderManager` 存在于明确 Provider
  配置模块；State 的权威字段和 View 的只读边界由测试保护。
- [ ] AC2：源码中不再存在 `AgentLifecycle` / `AgentLifecycleHost`；Agent 的 Provider
  配置字段不再作为可变实例存储，Manager 不 import 或接收 Agent。
- [ ] AC3：所有配置/Thinking 命令通过窄依赖完成，replacement 构建失败时旧 Provider、
  State、Runtime、history、派生服务和 recorder 均保持不变。
- [ ] AC4：成功切换遵守“构建 replacement → replace runtime → commit State → refresh
  Context/Memory/cache → record → async close old provider”的顺序。
- [ ] AC5：model-only 不重建 Provider；协议/credential/base/Thinking 切换重建并刷新
  compactor、Memory query 和 model-limit cache；Runtime identity 与 canonical history
  不变。
- [ ] AC6：restore 通过 Manager command 恢复 model/thinking，保留既有 JSONL entry 和
  thinking compatibility/coerce 语义。
- [ ] AC7：`create_provider` patch seam、Provider factory tests、integration tests、
  application facade、child Agent credential inheritance 和全量质量门禁通过。

## Out of Scope

- Memory Host / Memory ownership 的进一步拆分或重构；本任务只使用已有
  `MemoryQuerySink.set_query_service` 窄入口。
- Capability PromptLayer、AgentBuilder、SubagentFactory、Core history/JSONL schema、
  TUI/application UX、权限/预算/取消和其他 Host 协议的迁移。
- 引入 Provider registry、配置持久化新格式、migration/fallback compatibility layer 或
  第二份 active Provider/history。

## Planning Status

阻塞问题为空。用户已明确目标、事务顺序、兼容 seam、测试要求和排除范围；复杂任务所需
的 `design.md`、`implement.md` 以及 sub-agent context manifests 已准备，等待用户批准
最终规划摘要后才能启动实现。
