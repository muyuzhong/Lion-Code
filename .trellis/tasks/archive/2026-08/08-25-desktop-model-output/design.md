# 设计：桌面客户端模型输出闭环

## 1. 诊断顺序与证据等级

先建立一个不会依赖真实第三方网络的本地 Provider fixture。fixture 支持三种响应：

```text
valid OpenAI SSE → text delta → finish → [DONE]
HTTP error       → status/body
silent response  → 首个有效 SSE 前持续等待
```

真实 Electron 测试通过配置 UI 或同一受保护 REST 写入本地 endpoint，发送一次 prompt，并同时记录：

```text
Renderer action
  → WebSocket prompt
  → bridge/session event types
  → Provider HTTP request/response
  → assistant event
  → Renderer message + isStreaming=false
```

判断根因时以“Provider fixture 收到请求”和“最后一个下行事件”作为分界：

- 未收到请求：查 sidecar 配置/Session/Provider 构造，不先改 Renderer。
- 收到请求但无响应：查 timeout、连接和 endpoint 形态。
- 收到 HTTP/SSE 错误但页面不 idle：查 bridge、严格 decoder 或 reducer。
- 收到合法 assistant 事件但页面无文本：查 shared protocol 投影。

## 2. 失败终态设计

- 正常 Provider 错误继续走 canonical `AssistantMessage(stop_reason="error")` 和现有 assistant error 投影。
- Provider stream 必须有明确的请求/首响应边界；超过边界时生成结构化 Provider error，不让 `async for response.aiter_lines()` 无限占用 Session。
- bridge 捕获的未结构化异常必须经过现有 `server_error` 边界安全下发，并确保 active run 被消费；不把异常静默留在后台 task。是否补充 `agent_settled` 只按现有协议契约和失败测试结果决定，避免伪造正常完成事件。
- Renderer 以既有 `server_error`/`protocol_error`/assistant error 归位；若错误期间已有 provisional assistant，只保留一个非 streaming 的错误消息，允许下一次 prompt。

## 3. Provider 请求兼容边界

- 先验证当前 `/chat/completions` 路径、鉴权、模型、stream 字段和 SSE parser 的实际闭环。
- 若 fixture 或真实格式证明 `stream_options`、`store`、最大 token 字段、reasoning 字段或工具字段导致兼容失败，只在已有 `compat` 入口上修复契约或默认值；不为单一第三方名称添加分支。
- HTTP body 和异常文本经过现有安全错误格式化；测试只断言状态/安全诊断，不把 key 写进日志或快照。

## 4. 状态所有权

- Python sidecar 继续拥有 Provider、凭证、模型、Session canonical state。
- `LionAssistantRuntimeAdapter` 继续是 REST/WS 到 assistant-ui 的唯一 Renderer projection owner。
- 不把 timeout、Provider response 或消息历史写入 localStorage，不新增第二条持久化路径。
- 不触碰主进程 protocol 或用户已有未跟踪资源。

## 5. 测试矩阵

| 场景 | Provider HTTP | WS 关键事件 | UI 断言 |
|---|---|---|---|
| 已配置成功 | 合法 SSE 文本与 `[DONE]` | assistant start/update/end、settled | assistant 文本可见、发送框 idle |
| HTTP 失败 | 4xx/5xx | assistant error 或安全 server error | 错误可见、idle、无 key |
| 连接/首响应超时 | 本地服务不产生有效首事件 | timeout error | 在规定边界内 idle |
| 非法 SSE | 200 + 非法 JSON/无终端 | assistant error | 错误可见、可再次发送 |
| 未配置 API | 不发 Provider 请求 | assistant error、settled | 既有“API 未配置”回归继续通过 |
| 失败后重试 | 第二次返回合法 SSE | 新一轮完整事件 | 第二次回答可见 |

## 6. 风险与回滚

- 最小修复优先落在 Provider stream；只有测试证明事件/投影丢失时才改 Session、bridge 或 Renderer。
- 任何缩短 timeout 的改变都必须在测试中证明正常慢流仍可完成，并记录默认值与取消语义。
- 不改变配置 JSON 结构和已有 API key 保存策略；若实现阶段无法从本地 fixture 判定用户的真实 endpoint 问题，则停止扩大范围，向用户索取脱敏 endpoint 形态和等待时长。
