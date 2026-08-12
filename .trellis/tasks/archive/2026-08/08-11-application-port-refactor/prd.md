# Application Port 架构重构

## Goal

让 `LionCodingSession` 只依赖 application 消费者定义的稳定 Port，不再持有
`Agent`、`LionAgentRuntime`，也不再读取或调用 `AgentHarness`。TUI/CLI 继续通过
`LionCodingSession` 获取会话能力，Agent/runtime 通过窄 facade 实现这些 Port。

## Background and confirmed facts

- `lion_code/application/session.py::LionCodingSession` 当前保存 `_agent` 与
  `_runtime`，并直接使用 `_runtime.harness.queued_messages`、`steer`、`follow_up`。
- 同一文件还直接依赖 Agent 的 prompt、continue、abort、session lifecycle、provider
  settings、thinking、notice/approval callback 与 Session Memory 方法。
- `LionAgentRuntime` 已经是 AgentHarness 的持有者和 runtime 侧边界；Harness 类型只应
  在 core/runtime 实现内部出现。
- application 已拥有稳定的 `LionSessionEvent` 与 settled/overflow 事件语义；本次只
  替换其底层调用边界，不重写 Agent Loop 或事件协议。
- 当前工作区存在与本任务无关的 Trellis/.claude 配置 WIP；本任务只修改下列实现、测试、
  架构门禁和本任务 artifacts。

## Requirements

### R1. Consumer-defined ports

新增 `lion_code/application/ports.py`，按语义拆分小型 `Protocol`：

- `ConversationPort`：canonical `messages`、`subscribe`、`prompt`、`continue_`、
  `steer`、`follow_up`、`queue_snapshot`、`cancel`、取消状态与 overflow compact。
- `SessionPort`：`session_id`、list/resume/restore-latest/new-session、manual compact、
  close。
- `SettingsPort`：cwd、model、provider name、permission mode、API configured、provider
  config/configure、thinking level 读写与循环。
- 需要时再用小型 `UsagePort`、`ControlPort`、`SessionMemoryPort` 承载当前
  `LionCodingSession` 已经公开的用量、回调/Plan 和 task/memory 命令能力；禁止创建
  一个无语义边界的巨大 Port。

定义不可变的 `QueueSnapshot`，只包含 `tuple[str, ...]` 的 steering/follow-up 文本，
application 不接触 Harness 的 `queued_messages` 或 `AgentMessage` 队列容器。

### R2. Application depends only on ports

- `LionCodingSession.__init__(backend: CodingSessionBackend, ...)` 保存 `_backend`。
- `lion_code/application` 不导入 `Agent`、`LionAgentRuntime`、`AgentHarness`，不访问
  `.harness`，不读取 `core_runtime`。
- subscribe、messages、prompt、continue、steer、follow-up、queue snapshot、cancel、
  overflow compaction 全部经过 Port。
- application 自己继续拥有 settled 语义、事件桥接和“overflow 后最多 retry 一次”的策略。

### R3. Runtime facade and composition

- Agent/LionAgentRuntime 增加窄的语义 facade，内部可以继续持有并使用 Harness。
- facade 返回 application 所需的 queue snapshot，不泄漏 Harness 队列类型。
- runtime/core 不反向导入 application ports；使用 structural typing。
- 不重写 Agent Loop、Core Harness、canonical history、SessionRecorder 或 Memory overlay。

### R4. Tests and executable architecture guards

- 新增 `FakeCodingSessionBackend`，application unit tests 不构造真实 Agent。
- 覆盖 prompt event bridge、steering/follow-up、queue snapshot、cancel、overflow →
  compact → retry、retry 期间 abort、settled semantics、session operations、settings
  operations。
- 真实 Agent 集成回归单独保留。
- 增加架构测试，断言 application 不 import Agent/Harness/runtime、不访问 `.harness`，
  TUI 不直接 import runtime engine，runtime 不 import application，Fake backend 可直接
  注入 `LionCodingSession`。

## Out of scope

- 重写 Agent Loop、Core Harness 或 provider/tool loop。
- 引入第二套消息状态、Service Locator、通用 Runtime facade 或兼容迁移层。
- 把 overflow policy 全部下沉到 runtime；application 仍决定是否 compact/retry。
- 改造 CLI 的其他 autonomy/goal/loop 业务逻辑，除非只是把构造参数接到新的 backend
  入口。

## Acceptance criteria

- [ ] `LionCodingSession` 的源代码不存在 `_agent`、`_runtime`、`AgentHarness`、
      `core_runtime` 或 `.harness` 访问。
- [ ] Ports 位于 `lion_code/application/ports.py`，且每个 Port 只承载一个语义责任。
- [ ] 生产 Agent/runtime 可以作为 `CodingSessionBackend` 注入，TUI/CLI 行为不变。
- [ ] Fake backend 单元测试完全不 import/构造 `Agent`，覆盖 R4 所列行为。
- [ ] 真实 Agent integration tests 仍覆盖事件闭环与至少一条 overflow/session 路径。
- [ ] executable architecture tests 覆盖四条方向约束。
- [ ] `pytest`、`ruff check`、`mypy`、`compileall`、`lint-imports --no-cache`、
      `git diff --check` 通过；不把既有无关 dirty files 纳入本任务提交。

## Open questions

无。QueueSnapshot 的具体实现位置以 design.md 的依赖方向决策为准，外部契约仍从
`lion_code.application.ports` 暴露。
