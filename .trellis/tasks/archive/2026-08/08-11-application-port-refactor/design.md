# 技术设计：Application Ports

## Boundary

```text
TUI / CLI
    ↓ 仅持有 LionCodingSession
LionCodingSession
    ↓ CodingSessionBackend = 多个小型 application Protocol
Agent facade / LionAgentRuntime facade
    ↓
AgentHarness / Core / Provider / ToolRuntime
```

`LionCodingSession` 是 application policy owner：它负责事件队列桥接、
`AgentSettledEvent`、overflow 错误识别、一次 compact + retry 以及 retry 期间的
aborted 判断。它不负责选择 Harness、读取 Harness 队列或理解 runtime 的内部对象图。

## Port contracts

`lion_code/application/ports.py` 定义以下协议：

### ConversationPort

提供 canonical `messages` 快照、事件订阅和运行原语：

```python
messages -> tuple[AgentMessage, ...]
subscribe(listener) -> unsubscribe
prompt(content) -> Awaitable[None]
continue_() -> Awaitable[None]
steer(content) -> QueueSnapshot
follow_up(content) -> QueueSnapshot
queue_snapshot() -> QueueSnapshot
cancel() -> None
cancelled -> bool
compact_for_overflow() -> Awaitable[bool]
```

`prompt`/`continue_` 只驱动底层运行，事件仍通过 `subscribe` 到达 application 的
`asyncio.Queue`；这样保留当前“先排空事件，再发送 Settled”的行为。

### SessionPort / SettingsPort

`SessionPort` 只拥有 session identity、repository lifecycle、manual compact 和 close。
`SettingsPort` 只拥有前端需要的 cwd/provider/model/permission/API/thinking contract。
`UsagePort`、`ControlPort`、`SessionMemoryPort` 分别承载已有的 usage、approval/notice
callbacks/plan 与 task/memory command facade，避免把这些能力塞进一个 god object。

Queue snapshot 是纯文本、不可变、无 runtime 依赖的值对象。为满足 runtime 不反向导入
application，值对象放在 protocol-neutral 的 `lion_code.core.conversation`，并由
`application.ports` 作为 application port 的公开类型重新导出；application 不会暴露
`QueuedMessages`，runtime 只依赖 Core 值对象。

## Runtime implementation

在 `LionAgentRuntime` 增加 `queue_snapshot`、`steer`、`follow_up` 等 semantic facade，
由 facade 在内部把 Harness `AgentMessage` 队列转换为纯文本 `QueueSnapshot`。Agent 再
暴露 application 所需的 prompt/continue/cancel/session/settings/control/memory facade，
使现有 `Agent` 可以通过 Python structural typing 满足 `CodingSessionBackend`，无需让
runtime import application ports。

所有 Harness 访问继续留在 runtime/core 实现中；application 只调用 facade 方法。

## Application changes

- 用 `_backend` 替换 `_agent`、`_runtime`。
- `queue_update_event()` 直接读取一次 `backend.queue_snapshot()`，避免两次独立读取。
- provider configure 后不再重新绑定 `_runtime`；backend 自己保持 runtime 绑定。
- overflow retry 改用 `backend.compact_for_overflow()`、`backend.cancelled`、
  `backend.continue_()`。
- 保留现有 `LionCodingSession` 对外 API，TUI/CLI 不需要知道底层替换。

## Test design

- `tests/application/fakes.py` 提供可编排事件、队列、取消、compact 和 settings/session
  状态的 `FakeCodingSessionBackend`。
- application tests 只依赖 fake 和 core/application event models；不 import `Agent`。
- 现有真实 Agent 流程移动/保留为 integration scope，验证 facade 与真实 Core 的事件、
  session persistence 和 overflow behavior。
- `tests/architecture/test_application_ports.py` 使用 AST 检查 import direction、
  `.harness` 属性访问、Application→runtime 依赖和 Fake 注入路径。

## Compatibility and rollback

- 不保留 application 对旧 `_agent`/`_runtime` 的兼容属性；旧实现直接删除。
- Agent 的已有 runtime/core 内部 API 保持不动，只添加语义 facade，以降低底层行为风险。
- 回滚点是本次 Port/application facade 变更的单一工作提交；不触碰当前无关 Trellis WIP。
