# Research: composition and checkpoint boundary

- Query: 确认 Profile/Agent 的公开运行 seam、事件/结果契约、session artifact 与 checkpoint 的边界，以及 PR10 可以注入而不能反向依赖的对象。
- Scope: internal
- Date: 2026-08-17

## Findings

### 1. Profile and Agent construction

- `MinimalProfile`、`CodingProfile`、`FullProfile` 是冻结配置值，只描述 capability、skill、subagent 和 plan 组成；它们没有 goal、loop、retry、scheduler 或 Supervisor 字段（`lion_code/composition/profiles.py:35-110`）。
- `build_agent_composition(profile)` 构造一次 Agent/Harness 的具体运行图，并返回包含 runtime coordinator 等具体对象的 `AgentComposition`（`lion_code/composition/agent_builder.py:223-312`）。它是 Agent 构造根，不是长期任务调度器；Supervisor 不能持有或穿透这个 composition。
- `Agent` 当前负责公开的一次运行、事件订阅、session id、restore、cancel 和 close，但没有 `_autonomy`、goal 或 loop 入口（`lion_code/agent.py:381-440,580-597,628-674`）。因此长期行为应通过外部组合产生，不应恢复旧 Agent facade 方法。
- `MetaAgent` 提供同样窄的公开 facade：`run`、`subscribe`、`session_id`、`restore`、`cancel` 和 `close`，其 factory 只选择 Minimal/Coding profile（`lion_code/meta_agent.py:40-110,180-230`）。这证明测试 double、MetaAgent 和 Agent 都可以实现同一个 structural port。

### 2. Public event and result seam

- `core.events.AgentEvent` 是公开的 discriminated event union，覆盖 Agent/turn/message/tool/compaction/failure/cancel 生命周期（`lion_code/core/events.py:15-110`）。`core.harness.AgentHarness.subscribe` 接收 `AgentEvent` listener 并返回 unsubscribe callback（`lion_code/core/harness.py:120-152`）。Supervisor 应只消费这些公开值，不读取 harness、registry、transcript 或 coordinator。
- `tests/core/test_event_contract.py` 明确将这个 event contract 定义为未来 Supervisor 可以消费的公共 seam，并校验十类 public event；PR10 应在此基础上增加 Supervisor 的阶段映射测试，而不是暴露私有 runtime。
- `AgentRunResult` 还携带 `session_id`、`stop_reason`、`error`、计时和 usage 等字段（`lion_code/agent_runtime.py:75-87`），但该模块是 Agent/Harness 实现层。Supervisor 只定义一个 structural public-result protocol，读取 session id、stop reason 和 error；不导入 `lion_code.agent_runtime`，不保存 final text、messages 或 usage。

### 3. Session artifacts are not Supervisor state

- `SessionRecorder` 和 `SessionRepository` 负责 canonical session JSONL 的追加、重放和 compaction/session entry；它们保存 Agent 对话历史，不是 execution-control checkpoint（`lion_code/session_runtime/recorder.py:22-65,93-121`；`session_runtime/repository.py:14-60`）。Supervisor 只保存 session id/reference，不能把 transcript 或 message history 复制进自己的 state。
- `Agent.restore_session_id`/`restore_latest_session` 是公开的 session-history restore seam。Supervisor 可以在新 attempt 前请求 restore(session id)，但恢复失败应转为公开运行失败/重试决策，不应访问 session repository 的内部记录。
- `benchmarks/agent_e2e/checkpoint.py` 和 `benchmarks/agent_e2e/orchestrator.py` 的 CheckpointStore 只服务评测任务结果，属于 benchmark harness；生产 Supervisor 不应 import 或复用它们。

### 4. Existing recovery boundary

- `LionCodingSession._drive` 已通过 application backend ports 订阅公开 Agent event，处理 context overflow、一次 compaction retry 和 `AgentSettled` UI 事件序列（`lion_code/application/session.py:321-470`；`lion_code/application/events.py:31-80`）。这是前台 session 的 Application policy，不是旧 Autonomy 的长期 Supervisor。
- PR10 的 Supervisor retry/recovery 只负责外部长期 attempt、backoff、checkpoint/resume；不改变 `LionCodingSession` 当前 overflow event ordering，也不把 application queue/UI projection 或 `AgentRuntimeCoordinator` 移入新模块。

## Decision

PR10 使用一个独立的 `lion_code.supervisor` 模块和注入式 structural `AgentPort`/`AgentFactory`。Factory 在模块外选择 Profile，Supervisor 只保存 goal、phase、attempt、status、session reference、retry metadata 和 timestamps。CheckpointStore 使用独立的严格 execution-control 文档，不复用 SessionRepository、SessionRecorder 或 benchmark checkpoint。

Supervisor 的成功/失败判定以 public result 为准；event stream 只用于公开阶段观测。进程在 `running` 状态退出时，下一次调用在安全 attempt 边界 restore session reference 后重新发起 goal，不假装 checkpoint 包含 Agent 私有 in-flight runtime。

## Not found / caveats

- 当前没有 production Scheduler、RetryPolicy、CheckpointStore 或 Supervisor AgentFactory；这些是 PR10 新增的最小契约，不存在需要兼容的旧 API。
- `core/session/memory.py` 的名称属于 canonical compaction entry，不是项目级 Memory system；本研究不把它纳入 Supervisor 依赖，也不建议为 checkpoint 改动它。
- 本研究只做只读源码/spec/测试审查并写入任务文件，未修改生产代码、测试、spec 或 workflow。
