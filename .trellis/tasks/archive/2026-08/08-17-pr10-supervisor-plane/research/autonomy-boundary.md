# Research: autonomy boundary

- Query: 审查当前 Lion 的 `autonomy.py`、`autonomy_runtime.py`、Agent 残余入口、工具/Auto Mode 接线、相关测试与架构门禁，区分真正的 Supervisor 行为、Agent/Harness 责任和应删除的历史残留。
- Scope: internal
- Date: 2026-08-17

## Findings

### 1. 当前层边界和实际调用图

- 当前 spec 已把 `autonomy_runtime.py` 放在 `Application/Supervisor` 层，同时明确这一层不得拥有 Core/Harness 容器或直接 JSONL 写入；`Agent`、`agent_runtime.py`、`composition/` 属于 Harness（`.trellis/spec/backend/four-layer-ownership.md:8-17`）。`runtime-boundaries.md` 也明确保留 `ModelQuery`、`TranscriptView`、`ConversationRunner`、`NoticeSink` 和 `AutonomyRuntime` 作为窄 seam（`.trellis/spec/backend/runtime-boundaries.md:80-90`）。
- PR7a 的已归档设计记录了当前真实状态：Autonomy 已从 Full Product、`Agent` facade、REPL/Application/TUI 命令图中拔出；独立 runtime 只是为未来 Supervisor re-home 暂留，不代表仍属于 Agent 产品图（`.trellis/tasks/archive/2026-08/08-16-pr7a-supervisor-product-detachment/prd.md:18-31`、`design.md:24-35`）。
- 当前生产代码中没有 Supervisor、Scheduler 或 Checkpoint 模块；按文件名扫描只有 `lion_code/providers/retry.py`。`autonomy_runtime.py` 没有生产组合入口，唯一的直接 `autonomy` 导入是它自身；`Agent` 的类字典中没有包含 `autonomy`、`goal`、`loop`、`auto` 的入口。不要为了 PR10 恢复旧 Agent API。

### 2. `autonomy.py` 中真正可复用的 Supervisor policy

| 逻辑 | 证据 | 边界判断 |
|---|---|---|
| Goal directive/evaluator protocol | `goal_directive`、评估 system prompt、transcript framing、`goal_judge_user_message`、保守的 `parse_goal_verdict` 位于 `lion_code/autonomy.py:20-88` | 属于 Supervisor 的 goal lifecycle policy，可复用；应由外部 Supervisor 驱动，而不是重新塞回 Agent。 |
| Goal iteration cap | `GOAL_MAX_ITERATIONS = 25` 位于 `lion_code/autonomy.py:91-93` | 属于 Supervisor 的安全终止策略；不能代替 durable attempt/status。 |
| Loop input/duration policy | `parse_duration_to_seconds`、`parse_loop_input` 位于 `lion_code/autonomy.py:112-157` | 属于 Scheduler/long-running control 的输入策略，可复用或改成明确的 Scheduler request。 |
| Dynamic wakeup policy | `clamp_wakeup_delay`、`dynamic_loop_directive`、`LOOP_MAX_ITERATIONS` 位于 `lion_code/autonomy.py:169-201` | 延迟校验、模型自排下一次运行和硬上限属于 Supervisor；工具适配器本身仍属于 tooling。 |

`AutonomyRuntime` 的状态与驱动循环证据如下：

- 初始化只接收 `ConversationRunner`、`TranscriptView`、`ModelQuery`、`NoticeSink`、`CancellationView`、`ToolRegistry`、confirm callback、`UsageLedger` 和 `BudgetPolicy`，不接收 `Agent` 或 `AgentRuntimeCoordinator`（`lion_code/autonomy_runtime.py:1-5`、`:52-76`）。
- Goal lifecycle 在 `set_goal`/`show_goal`/`pursue_goal` 中完整出现：设置 condition、iteration、start time、last reason；执行一次对话；side-query 评估；未满足时反馈原因并再次 `chat`；满足、不可能、预算超限或中断时停止（`lion_code/autonomy_runtime.py:92-178`）。`_evaluate_goal` 只把最近一条 assistant 文本作为 evidence，通过 `ModelQuery.complete_messages` 做独立判定（`:180-210`）。这些是旧实现中最明确的 Supervisor 行为。
- 固定间隔 loop 和动态 loop 都是 scheduler/long-running control：固定间隔每 tick 调用 `ConversationRunner.chat` 并检查 budget、`max_turns`、硬上限和可中断 sleep（`lion_code/autonomy_runtime.py:212-278`）；动态 loop 临时注册 wakeup tool，读取 pending wakeup，等待延迟并以新 prompt 继续（`:280-334`）。
- `schedule_wakeup` 只验证/裁剪参数并把 `delay_seconds`、`reason`、`prompt` 写入本次 runtime 的 `pending_wakeup`（`lion_code/autonomy_runtime.py:336-359`）。`stop_loop`/`stop_goal` 只是设置当前内存中的 stop flag（`:361-378`）。

这些代码还不是 PR10 所需的完整 durable Supervisor：

- Goal 是无类型 `dict`，只有 `condition`、`iterations`、`started_at`、`last_reason`；`finally` 无论结果如何都清掉 `active_goal`，注释明确“当前实现不支持恢复进行中的 `/goal`”（`lion_code/autonomy_runtime.py:94-101`、`:175-178`）。没有 phase、attempt、status、session/checkpoint id 或 retry metadata。
- Loop 的 wakeup、stop flag 和 tick counter 全部是进程内变量；固定 loop 明确标注 session-only，动态 loop 也不使用独立 evaluator，只有当前生命周期的 `schedule_wakeup`（`lion_code/autonomy_runtime.py:242-249`、`:280-285`）。这可以作为 Scheduler policy 的来源，但不能伪装成持久化 scheduler/checkpoint。
- `pursue_goal` 在 evaluator 返回未满足时再次执行，是“评估反馈后的下一次 goal turn”，不是通用错误 retry/recovery。Autonomy runtime 中没有 `RetryPolicy`、checkpoint store、resume orchestration、AgentFactory/Profile selection 或 Agent event/result orchestration。
- `run_loop` 对长间隔或 daily wording 只发“真实客户端会建议云计划”的教学提示，然后继续当前进程；项目没有云 scheduler backend（`lion_code/autonomy_runtime.py:220-231`）。这段提示和 `OFFER_CLOUD_THRESHOLD_SECONDS` 是产品教学残留，不应作为真实 Scheduler 能力迁移。

### 3. Agent/Harness、Application 和 Provider 的职责不能混入 Supervisor

- `Agent.__init__` 当前只将 legacy 参数归一化为 `AgentConfig`/`AgentDependencies`，构造 `FullProfile`，调用 `build_agent_composition`，再保存显式 composition 结果（`lion_code/agent.py:118-240`）。Composition 门禁明确禁止 Agent constructor 调用/构造 `AutonomyRuntime`，并禁止 `AgentComposition`/builder 出现 Supervisor surface（`tests/architecture/test_composition_root.py:148-170`、`:196-233`）。
- Agent 对外仍有 Core 公共 seam：`core_runtime`/`subscribe` 暴露事件订阅（`lion_code/agent.py:381-403`），`chat`、`run_once`、`run` 委托到 `AgentRuntimeCoordinator`（`:573-597`），`run` 的结果是含 session id、final text、stop reason、turns、tokens、cost、error 的 `AgentRunResult`（`lion_code/runtime/agent.py:63-87`、`:762-833`）。未来 Supervisor 应消费这些公共结果/事件和 session reference，不访问 Agent 私有字段。
- `AgentRuntimeCoordinator` 是 Agent/Harness 的 Core run owner：它负责 `AgentHarness`、动态 system/tools、ToolRuntime、Provider、取消、usage、context preparation、事件 capture 和单次 `chat` 时序（`lion_code/runtime/agent.py:107-143`、`:280-340`、`:431-493`、`:710-737`）。这些不是 Supervisor 的 goal/scheduler/retry 状态，不应迁移到新平面。
- Tool execution 仍是 Harness/tooling 责任。`ToolRuntime.execute` 解析 registry、执行 middleware、调用 `LionTool` 并把异常转成结构化 `ToolResult(is_error=True)`（`lion_code/tooling/runtime.py:28-94`）；`PermissionMiddleware` 只按通用 `ToolPermissionStrategy`、permission mode 和 confirm callback 决策（`lion_code/tooling/middleware.py:103-158`）。`Agent._execute_tool_call` 只是保留测试/嵌入 seam，直接调用 `tool_runtime.execute`，没有工具名分支（`lion_code/agent.py:701-718`）。
- Canonical session history 由 `SessionRecorder` append、`SessionRepository` replay；recorder 只保存完成态 `MessageEndEvent`，JSONL 记录的是对话/压缩历史而非 Supervisor execution-control state（`lion_code/session_runtime/recorder.py:22-65`、`:93-121`；`session_runtime/repository.py:14-60`）。`Agent.restore_session_id`/`restore_latest_session` 是会话历史恢复，不能当作 Supervisor checkpoint/resume（`lion_code/agent.py:628-674`）。

当前仓库中真正存在的 retry/recovery 和 event/result orchestration 在 Application，而不在旧 Autonomy：

- `LionCodingSession._drive` 订阅 backend 的公开 `AgentEvent`，等待协程和事件队列排空，识别 canonical context overflow，调用窄 port `compact_for_overflow()`，最多续跑一次 `continue_()`，发 `AutoRetryStart/End`，最后发 `AgentSettledEvent`（`lion_code/application/session.py:321-470`）。
- 对应的 application event contract 明确 `AgentEnd` 不等于 UI 可归位，事件顺序是 `SessionAgentEnd → CompactionStart → CompactionEnd → AutoRetryStart → retry events → AutoRetryEnd → AgentSettled`（`lion_code/application/events.py:1-15`、`:31-80`）。现有 spec 也把 event bridge 和“一次 context-overflow compact/retry”归给 Application（`.trellis/spec/backend/runtime-boundaries.md:64-70`、`four-layer-ownership.md:26-36`）。
- 因此，PR10 要求的 Supervisor retry/recovery/event/result orchestration 应从这个公开 port/event 事实出发；不能把整个 `LionCodingSession` 前端桥或 `AgentRuntimeCoordinator` 搬进 `AutonomyRuntime`。至少要保留应用层的 UI-specific `Settled`/queue projection 与 Agent/Harness 的 primitive compaction。
- Provider 的 HTTP/backoff retry 是另一条边界：`lion_code/providers/retry.py:16-63` 和 Anthropic/OpenAI streaming envelope（如 `lion_code/providers/openai_compatible.py:196-201`、`:225-312`）只负责一次 provider request 的传输重试，不是 Supervisor 的任务重试。

### 4. 工具和 Auto Mode 的真实接线

动态 wakeup 的状态 owner 是 Autonomy，但 tool adapter 不是 Autonomy state：

- `create_wakeup_tool(command)` 在 `lion_code/tooling/internal.py:157-191` 只把窄 `ToolCommand` 包装为 `LionTool`；`create_internal_tools` 只常驻 `tool_search`，并明确 `schedule_wakeup` 由动态 loop 临时注册（`:194-203`）。
- Autonomy 在动态 loop 生命周期内用 `ToolRegistry.temporary_tool` 绑定 `self.schedule_wakeup`（`lion_code/autonomy_runtime.py:290-299`）；退出时清理 pending state（`:333-334`）。`ToolRegistry.temporary_tool` 的精确注册/恢复语义是通用 Harness/tooling 行为（`lion_code/tooling/registry.py:103-119`）。未来 Supervisor 只应提供 wakeup command/state，不能获得完整 ToolRuntime 或 registry service locator。
- 架构测试已要求 tooling 不得 import `PlanRuntime`/`AutonomyRuntime`，并禁止 `ToolContext` 携带 auto/plan 业务字段（`tests/architecture/test_runtime_boundaries.py:1332-1345`）。工具路由门禁还禁止旧的 `AgentToolController`、`context.controller` 和 `schedule_wakeup_tool` 名称残留（`tests/architecture/test_tool_routing.py:10-18`、`:57-73`）。

Auto Mode 不是 Supervisor，而是一次工具调用的权限/安全决策，而且当前没有真实生产接线：

- `AutonomyRuntime._classify_tool_call` 读取 ToolRegistry、transcript、`CLAUDE.md`，运行两阶段 side-query classifier，维护连续/累计 denial，最后 allow/deny/confirm（`lion_code/autonomy_runtime.py:380-463`）；`is_auto_fast_path` 只按 ToolCapabilities 跳过无副作用只读工具（`:47-49`）。这属于 Tool/Permission policy，不属于 goal、scheduler、retry 或 long-running control。
- `set_confirm`、`auto_consecutive_denials`、`auto_total_denials` 和 `_auto_fallback` 只服务该分类器（`lion_code/autonomy_runtime.py:77-90`、`:442-463`）。当前 Agent/ToolRuntime 没有调用 `_classify_tool_call`；通用 PermissionMiddleware 没有 Auto 分支，架构测试还显式禁止 permission state/middleware 出现 `"auto"` 语义（`tests/architecture/test_runtime_boundaries.py:1314-1329`、`:1416-1423`）。
- `load_auto_mode_rules` 依赖 `assets/auto-mode-rules.json`（`lion_code/autonomy.py:218-236`），但该文件当前不存在；`autonomy.py` docstring 所指 `_reference/` 和 `how-claude-code-works/` 目录也不存在。`providers/oneshot.py` 仅在模块说明中提到“评估器、Auto Mode 分类器”可复用 side-query（`lion_code/providers/oneshot.py:1-16`），不是接线证据。
- 结论：Auto Mode classifier 全部是孤立历史残留，应删除而不是迁移到 Supervisor。若将来重新产品化，应另做 tooling/permission policy 设计；不要用 Supervisor 绕过 permission boundary，也不要为旧 Agent API 加 fallback/compatibility layer。相应纯 helper、规则解析和只为它服务的测试可一并删除或另立安全策略任务。

### 5. 测试现状和架构门禁

- `tests/test_autonomy.py:9-89` 仍执行 goal/loop parser、wakeup clamp、goal verdict 和 Auto Mode transcript/parser 的纯逻辑测试；它只能证明 helper 自洽，不能证明生产接线。
- `tests/test_autonomy_goal_loop.py` 明确以 `_REHOME = "等待 Supervisor composition 重新接入 Autonomy"` 标记待迁移行为（`:24`、`:41-43`），但 fixture 仍写入 `agent._autonomy`、替换 `agent.chat` 并断言 `Agent.set_goal`/`Agent.pursue_goal`（`:27-38`、`:49-111`）。这些类整体 skip 是历史残留的证据，不应据此恢复 Agent facade。
- `tests/test_autonomy_flow.py` 同样以 `_REHOME` skip Agent/Auto Mode flow（`:23`、`:42-56`），直接使用 `agent._autonomy`（`:38-39`、`:80-87`）；其规则文件依赖还由 `HAVE_DEPS` 控制（`:21`、`:90-92`）。`tests/tooling/test_agent_internal_runtime.py:52-67` 的 dynamic loop test 也 skip，并依赖 `agent._autonomy`；相反，`tests/tooling/test_internal_tools.py:96-108` 和 `tests/tooling/test_temporary_tools.py:14-26` 仍有效覆盖 wakeup adapter/temporary registry 的通用行为。
- 本轮定向执行 `tests/test_autonomy.py`、`test_autonomy_flow.py`、`test_autonomy_goal_loop.py` 及相关 architecture tests：22 passed、17 skipped。跳过集中在 `_REHOME` 与缺失 Auto Mode 规则，说明当前没有 goal/loop 的端到端 Supervisor 验证。
- `tests/architecture/test_kernel_isolation.py:19-43` 把 `autonomy_runtime.py` 视为 Supervisor module，禁止 Kernel 引用 Autonomy，并禁止 Supervisor import `lion_code.agent`、`agent_runtime`、`core.harness` 或触碰 `_aborted`、`core_runtime`、`_runtime_coordinator`（`:63-107`）。
- `tests/architecture/test_runtime_boundaries.py:1820-1894` 检查 AutonomyRuntime 无 Agent/Host 构造参数、无 service locator、无 `_core_runtime`/`_host`；`:1332-1345` 检查 tooling 反向依赖。`tests/architecture/test_bare_composition.py:60-87` 把 AutonomyRuntime 列为 Bare 图不得出现的 feature；`tests/architecture/test_composition_root.py:210-233` 当前明确要求 Composition Root 没有 Supervisor surface。
- `pyproject.toml:114-182` 的 import-linter 禁止 Core/Providers 反向导入 `autonomy`/`autonomy_runtime`，`tests/core/test_event_contract.py:59-74` 也保持 Kernel→Supervisor 单向依赖。`tests/architecture/test_legacy_memory_removal.py:11-81` 对 Memory/SessionMemory/Dream/Learning 的模块和符号实行负向门禁，并明确允许 `core/session/memory.py` 的 CompactionEntry。
- 现有门禁主要是负向边界检查；没有门禁证明 Autonomy 已经消费 Agent 的公开 event/result，而不是 `ConversationRunner.chat` + `TranscriptView.messages`。PR10 实现前需要新增/收紧正向契约测试，但不应通过放宽当前 Agent/Composition 禁止项来接线。

### 6. 建议的处置矩阵

| 旧逻辑/位置 | 处置 | 原因 |
|---|---|---|
| Goal evaluator、goal verdict parser、goal stop/feedback policy (`autonomy.py:20-93`; `autonomy_runtime.py:94-210`) | 迁入独立 Supervisor，改接公开 Agent event/result 与 durable goal state | 这是实际 Supervisor 行为，但当前 state 非 durable、直接读 transcript、不能 resume。 |
| Interval/dynamic loop、delay clamp、wakeup request (`autonomy.py:112-201`; `autonomy_runtime.py:214-378`) | 迁入 Scheduler/Supervisor policy；保留 `create_wakeup_tool` 这种窄 tooling adapter | 这是实际 scheduler/long-running control；当前仅 session-local，不是持久化 scheduler。 |
| `ToolRegistry.temporary_tool`、`ToolRuntime`、middleware、`Agent._execute_tool_call` | 留在 Harness/tooling | 它们提供通用 registry/execution/permission 机制，不应被 Supervisor 持有为私有 runtime。 |
| Agent `chat`/`run`/`abort`、`AgentRuntimeCoordinator`、SessionRepository/Recorder | 留在 Agent/Harness/session ownership，作为 Supervisor public ports/reference | 这些是一次 Agent 执行、事件、canonical history 与会话恢复，不是 Supervisor goal/control state。 |
| `LionCodingSession._drive` 的一次 overflow compact/retry 与 application event mapping | 识别为现有 retry/recovery/event orchestration；按 PR10 目标抽取语义窄 port，保留 UI-specific bridge | 它已经通过公开 backend/event seam 工作，但当前是 Application policy，不是旧 Autonomy。 |
| Provider HTTP retry (`providers/retry.py`, provider streaming envelope) | 留在 Provider | 只重试单次传输请求，不拥有长期任务状态。 |
| Auto Mode classifier、规则加载、transcript projection、denial counters/fallback | 删除，不迁移到 Supervisor | 没有生产 caller、规则资产缺失，且本质是工具权限决策；迁入 Supervisor 会错误扩大职责。 |
| `/goal`、`/loop`、`Agent._autonomy` 兼容入口 | 不恢复；删除/更新 stale tests | PR7a 已按无兼容层策略从 Agent/CLI/Application/TUI 删除，当前测试用 `_REHOME` 明确等待新 composition。 |
| 云端 schedule suggestion (`is_daily_wording`、`OFFER_CLOUD_THRESHOLD_SECONDS`) | 删除或另立真实 cloud-scheduler 任务 | 当前只有教学提示，无 backend、durable artifact 或可恢复执行。 |

## Related specs

- `.trellis/spec/backend/four-layer-ownership.md:8-17,26-47`：四层 owner、Application overflow retry 和 canonical session ownership。
- `.trellis/spec/backend/runtime-boundaries.md:13-17,31-47,64-90`：Composition Root、状态 owner、Application ports、Autonomy retained seams。
- `.trellis/spec/backend/usage-ownership.md:66-75,117-124,141-152`：Agent public `UsageSnapshot`/`AgentRunResult` 边界；Autonomy re-home 不得创建第二个 usage/budget owner。
- `.trellis/spec/backend/capability-spi.md:39-61`：CapabilityRegistry 只是聚合器；Capability 不得恢复 Agent/service locator 或 Memory/Dream/Learning 图。
- `.trellis/spec/backend/error-handling.md:37-60`：现有 context-overflow one-retry contract 和取消/异常语义。
- `.trellis/tasks/archive/2026-08/08-16-pr7a-supervisor-product-detachment/{prd.md,design.md}`：已完成的 Supervisor product detachment 与无兼容层/re-home 规则。

## External references

- `lion_code/autonomy.py:1-5` 声称依据 `_reference/{goal,loop,auto-mode}-reverse-engineering.md` 和 `how-claude-code-works/docs/18-auto-mode.md`，但当前 checkout 中 `_reference/`、`how-claude-code-works/` 均不存在；本研究未将这些不可读取的文档当作当前事实。
- 当前仓库未声明与 Autonomy/Scheduler 相关的外部库版本；结论基于当前 on-disk Python、测试、spec 和 import/AST 门禁。

## Caveats / Not Found

- 没有找到当前生产 Supervisor composition、Scheduler abstraction、CheckpointStore、RetryPolicy、Supervisor AgentFactory 或 goal/loop 的公开 Agent event/result adapter；PR10 仍需要建立这些外部契约。
- `SessionRepository`/JSONL 中的 `core/session/memory.py` 是 canonical compaction entry，不是被 PR9 删除的 project Memory；不得因为 PR10 checkpoint 需求删除它，也不得把对话内容当作 execution-control checkpoint。
- `autonomy_runtime.py` 当前虽然通过 architecture gate 避免了 `Agent`/`agent_runtime` import，但仍直接依赖 `ConversationRunner`、`TranscriptView`、`ToolRegistry` 和 `UsageLedger`；这证明它是已拆窄的旧 in-process runtime，不等于已经满足 PR10 的外部 event/result + durable checkpoint 边界。
- 本轮只做只读源码/spec/测试审查并写入本研究文件；未修改生产代码、测试、spec、workflow 或其他 task 文件。
