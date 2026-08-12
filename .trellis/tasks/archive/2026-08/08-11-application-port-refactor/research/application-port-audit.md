# Application Port 代码审计

## 现状证据

- `lion_code/application/session.py:77-80` 构造函数接收 `Agent`，保存 `_agent`，再缓存
  `agent.core_runtime` 到 `_runtime`。
- `lion_code/application/session.py:123-137` 从 `_runtime.messages` 和
  `_runtime.harness.queued_messages` 读取 canonical transcript 与 Harness 队列。
- `lion_code/application/session.py:160-180` 在运行中直接调用
  `_runtime.harness.steer/follow_up`，空闲路径调用 `Agent.chat` 和 runtime `continue_`。
- `lion_code/application/session.py:183-212` 直接调用 Agent 的 abort/close/session/compact/
  usage 方法。
- `lion_code/application/session.py:216-260` 直接调用 Agent 的 provider 与 thinking API，
  configure 后还重新读取 `agent.core_runtime`。
- `lion_code/application/session.py:302-341` 直接调用 Agent 的 Session Memory、approval、
  notice 和 Plan API。
- `lion_code/application/session.py:353-486` 事件桥接、overflow compaction、aborted 判断
  与 retry continue 直接依赖 `_runtime` 和 `_agent`。

## 可复用的 runtime 能力

- `lion_code/agent_runtime.py:105-206` 的 `LionAgentRuntime` 已持有 Harness，并提供
  subscribe、prompt、continue、cancel、messages 等运行基础能力。
- `lion_code/agent.py:579-700` 已提供 abort、overflow compaction、terminal output、
  provider、thinking、usage 和 callback 能力。
- `lion_code/agent.py:761-1038` 已提供 clear/compact、dream、session restore/list 等
  lifecycle 能力。
- `lion_code/core/harness.py:91-175` 说明 Harness 的 `QueuedMessages` 包含
  `AgentMessage`，因此不能直接出现在 application contract。

## 约束

- `tests/architecture/_boundaries.py` 当前已有 Application 不依赖 TUI、TUI 受限于
  Application/Core、Core 不依赖上层的 import contracts；本任务增加更细的 AST guards。
- 当前 `tests/application/test_coding_session.py` 以真实 Agent + FakeProvider 驱动，适合
  作为 integration regression；新的 application unit tests 应改用 Fake backend。
- `lion_code/application/__init__.py` 的文档已声明 TUI → application → runtime → core，
  需要改为 Ports 语义，避免文档继续暗示 application 直接组合 runtime。
