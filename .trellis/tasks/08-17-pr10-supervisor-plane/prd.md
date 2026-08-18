# PR10 Supervisor Plane

## Goal

建立一个独立的 Supervisor Plane，负责决定 Agent 的再次运行主体、时机和策略，
支持长期任务的 goal lifecycle、调度、重试/恢复和 checkpoint/resume，同时不把
Memory 重新引入执行控制链路。

## Confirmed Facts

- Legacy Memory / Dream / Learning 已经完整删除；本任务不恢复这些能力。
- Supervisor 是 Agent 外部的控制平面，主要消费 Agent Event Stream、Agent public
  result、Session ID 和 durable session artifacts。
- Supervisor 不得访问 Agent 私有 Runtime。
- `MinimalProfile`、`CodingProfile`、`FullProfile` 以及 Agent 本身都不知道
  Supervisor、autonomous loop、goal、retry 或 scheduler。

## Requirements

### R1. Supervisor ownership

Supervisor 只拥有以下职责：Autonomy、Goal lifecycle、Scheduler、Retry / Recovery、
Checkpoint / Resume orchestration、Long-running task control、AgentFactory / Profile
selection。

### R2. Explicit exclusion

Supervisor 生产代码及其依赖中不得包含 Memory、SessionMemory、Dream 或 Learning，
也不得通过 `MemoryRepository`、relevant-memory、semantic memory、user preference、
extracted knowledge、learned experience 或 memory embeddings 等形式保存或重建它们。

### R3. Durable execution-control state

Checkpoint / durable state 只能保存恢复执行所需的控制信息，例如 goal、current phase、
attempt、checkpoint/session id、status、retry metadata 和 timestamps。Checkpoint 只
表达“如何恢复执行”，不表达“Agent 应该记住什么”。

### R4. Event-driven boundary

Supervisor 通过 Agent 的公开事件流、公开结果和 session/checkpoint artifact/reference
驱动状态转移，不依赖 Agent 私有 Runtime。

### R5. Profile isolation

普通 profile 可以独立构造和运行；只有显式组合类似
`Supervisor(agent_factory=..., goal=..., retry_policy=..., checkpoint_store=...)`
的外部入口，才产生长期运行行为。

### R6. Autonomy review

现有 `autonomy.py` / `autonomy_runtime.py` 必须先按 Supervisor ownership 进行对抗式
审查：删除属于旧 Full Agent / Memory 架构的历史残留，仅复用真正属于 Supervisor 的
行为；不为保留旧 API 增加兼容层。

## Acceptance Criteria

- [ ] 存在独立的 Supervisor 生产边界，能基于公开 Agent 事件/结果和 session/checkpoint
      reference 编排再次运行。
- [ ] Supervisor 能表示并驱动 goal lifecycle、phase、attempt、status、retry/recovery
      和 checkpoint/resume；状态仅包含执行控制数据。
- [ ] Scheduler、retry policy、checkpoint store、AgentFactory/Profile selection 通过
      明确的外部契约组合，且不要求 Agent 或 profile 持有 Supervisor 状态。
- [ ] `MinimalProfile`、`CodingProfile`、`FullProfile` 的生产代码与测试仍可在无
      Supervisor 的情况下构造/运行，并且不出现 Supervisor 依赖。
- [ ] Supervisor 生产依赖闭包中对 Memory、SessionMemory、Dream、Learning 以及对应
      repository/embedding/experience 概念的静态门禁为 0。
- [ ] Agent 私有 Runtime 未被 Supervisor 直接访问；边界由测试或架构检查验证。
- [ ] 现有 autonomy 实现中不属于 Supervisor 的旧职责被删除或明确移出；无为旧 API
      保留而新增的 fallback/migration/compatibility layer。
- [ ] 定向测试、全量可运行测试、静态检查和项目架构门禁通过；与本任务无关的既有
      dirty worktree 基线失败单独记录，不被误报为本任务回归。

## Out of Scope

- Memory、SessionMemory、Dream、Learning 的任何实现、恢复、替代品或迁移层。
- extracted knowledge、user preference、semantic memory、relevant-memory、learned
  experience、memory embeddings 的持久化或检索。
- 修改普通 profile 的产品能力以承载 Supervisor。
- 为了 Supervisor 引入 Agent 私有 Runtime 访问、全局 service locator 或宽泛兼容层。

## Confirmed implementation decisions

- 新增唯一的独立生产边界 `lion_code.supervisor`。它通过注入的 structural
  `AgentPort`/`AgentFactory` 消费公开 Agent event、公开 result 和 session reference；
  Supervisor 不导入 `Agent`、`agent_runtime`、Harness/ToolRegistry/Provider/TUI 私有实现。
- `agent_factory` 在 Supervisor 外部选择并构造 `MinimalProfile`、`CodingProfile` 或
  `FullProfile`。Profile、Composition Root 和 Agent 保持零 Supervisor 字段、导入和构造
  分支。
- 新的 goal lifecycle 以 public result 的 `stop_reason` 判定成功/终态；event stream 仅
  提供公开阶段观测。旧的 transcript side-query/semantic goal judge 不迁移。
- `autonomy.py`、`autonomy_runtime.py` 中的旧命令解析、side-query、transcript classifier、
  Auto Mode、进程内 loop/wakeup 状态和仅为它们服务的窄适配器属于历史残留，直接删除；
  不恢复 `/goal`、`/loop`、`Agent._autonomy` 或兼容层。Supervisor 以新契约重建最小的
  goal、scheduler、retry 和 resume 行为。
- `domain_ports.py`、`model_query.py`、`providers/oneshot.py` 及其仅由旧 Autonomy 使用的
  路径在确认无生产消费者后删除；Provider request retry 和 Application 的前台
  context-overflow retry 保持原 owner，不并入 Supervisor。
- CheckpointStore 是独立的 execution-control store，严格拒绝额外字段，不复用
  `SessionRepository`、`SessionRecorder`、canonical session JSONL 或 benchmark checkpoint。
  running 状态恢复只在安全 attempt 边界 restore session reference 后重新运行，不保存
  Agent in-flight runtime snapshot。
- 计划中的验证以可观察边界为中心：公开 event/result 编排、retry/backoff、checkpoint
  load/save/resume、取消/终态、Profile 隔离、私有 Runtime 负向扫描和 durable 字段白名单。

以上决策均由当前源码、测试和 Trellis backend specs 确认，不保留未决的产品范围问题。

## Notes

- Existing `LionCodingSession` foreground overflow event bridge remains an Application-owned
  policy; changing it would expand PR10 beyond long-running Supervisor control.
- The detailed source evidence is recorded in `research/autonomy-boundary.md` and
  `research/composition-and-checkpoint-boundary.md`; the technical contracts and state
  machine are in `design.md`.
