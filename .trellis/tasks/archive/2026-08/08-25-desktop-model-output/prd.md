# 排查桌面客户端发送后无模型输出

## Goal

让 Electron preview 与后续安装包中的桌面客户端在已配置 Provider 后能够完成一次真实的模型流式对话；Provider 不可达、响应格式错误或请求超时必须显示可诊断的终态错误，并恢复发送框，而不是长期停留在“运行中”。

## Confirmed Facts

- `desktop/src/renderer/src/lionRuntime.ts::sendInput` 在 WebSocket action 发送成功后立即把本地 `isStreaming` 置为 `true`；只有协议终态、`server_error`、`protocol_error`、断开或取消等路径会清除它。
- `lion_code/server/bridge.py::SessionWebsocketBridge._drive_events` 只在事件迭代产生内容或抛出异常后向 WebSocket 转发；Provider 请求等待首个有效事件期间不会产生额外诊断。
- `lion_code/providers/stream.py::stream_provider_post` 在进入响应后等待 `response.aiter_lines()`；当前 OpenAI-compatible 默认 HTTP timeout 为 60 秒、最多重试 2 次。重试事件在 canonical provider stream 中不直接显示为 assistant 内容。
- 现有桌面真实 sidecar 回归覆盖未配置 API 的错误和配置读回，但没有覆盖“已配置 Provider → 本地 OpenAI-compatible SSE → Python 事件 → Renderer assistant 输出”的闭环。现有聊天 Playwright 场景使用 Fake WebSocket，Provider 单测使用 `httpx.MockTransport`。
- 截图只证明用户消息已进入本地会话且停止按钮处于运行态；没有提供 endpoint、模型服务响应、sidecar stderr 或 API key 信息。因此不能仅凭截图断定是 Provider payload、网络响应还是事件投影问题。
- 保留用户已有的 `desktop/src/main/protocol.ts` 修改和 `docs/assets/` 未跟踪文件，不纳入本任务。

## Root-Cause Hypotheses

按当前证据优先验证以下假设，不在验证前扩大改动：

1. **Provider 流等待无可见终态（高概率）**：连接或首个 SSE 长时间没有返回，Renderer 只能保持运行态，且默认重试窗口过长。
2. **Endpoint / payload / SSE 兼容性（中概率）**：自定义 OpenAI-compatible 服务拒绝当前 `/chat/completions` 请求，或返回当前解析器不会识别的流；现有闭环测试没有覆盖真实配置入口。
3. **跨层事件终态缺口（待排除）**：Provider 或 Session 异常经过 bridge 后只产生通用错误，或某个首个事件被严格 Renderer decoder 拒绝，导致用户看不到 assistant 结果。

## Requirements

### R1. 已配置 Provider 的真实输出

- 已配置的 OpenAI-compatible Provider 发送非空消息后，真实 sidecar 必须收到一次模型请求，并把合法 SSE 文本投影为可见 assistant 消息。
- 请求使用当前 Python canonical Provider、模型和会话历史；Renderer 不创建第二份 Provider 或消息状态。
- 正常流、工具调用路径和历史加载的现有协议语义保持不变。

### R2. Provider 失败必须终止且可诊断

- HTTP 非 2xx、连接失败、SSE 无效、响应无终端事件和超时都必须形成用户可见的 assistant 错误或等价终端错误。
- 错误必须在明确的请求/首响应超时边界内收敛，不能依赖多次无限等待；重试不得让 UI 永久保持运行。
- 错误信息不得包含 API key、capability 或未经脱敏的认证头；可保留安全的 Provider、状态码和非敏感诊断。

### R3. Renderer 状态可恢复

- 错误或取消后 `isStreaming` 归零、停止按钮消失、发送框重新可用。
- 失败后可以再次发送，不需要重启 sidecar 或刷新窗口。
- 真实 sidecar 异常与正常 assistant error 都遵循已有严格 WebSocket event decoder 和 assistant-ui 投影边界。

### R4. 真实回归与诊断

- 使用隔离的 `LION_SIDECAR_STATE_HOME` 和本地可控的 OpenAI-compatible SSE 服务验证成功、HTTP 错误、响应停滞/超时和再次发送。
- 测试同时观察 Provider HTTP 请求、WebSocket 事件序列、可见 assistant 内容和最终 idle 状态；不能只依赖 Fake WebSocket 或 Provider 单测。
- 若根因落在 payload/解析兼容性，增加最小的请求/响应契约回归；不针对某个真实第三方服务添加无证据的专用分支。

## Acceptance Criteria

- [ ] 从真实 Electron + Python sidecar 启动，配置隔离本地 OpenAI-compatible SSE 服务后发送 `hi`，页面显示预设 assistant 文本，发送框恢复 idle。
- [ ] 本地服务返回 4xx/5xx 或非法 SSE 时，页面显示非空错误，停止按钮消失，且错误文本不含测试 API key。
- [ ] 本地服务在首个有效响应前停滞时，请求在规定 timeout 内显示错误并恢复可发送；不需要等待多轮默认重试后才可见。
- [ ] 失败后再次发送能够产生新的 Provider 请求；不残留 `is_running`、`isStreaming` 或旧的 provisional assistant 运行态。
- [ ] 既有未配置 API 的真实 preview 错误、配置保存/读回、API key 掩码/查看和 Fake WebSocket 协议测试继续通过。
- [ ] 通过相关 Python/Renderer/Playwright 测试、桌面 typecheck/build；全量质量检查中的既有基线噪声单独记录。
- [ ] 不修改磁盘凭证格式、不实现磁盘加密、不改用户已有 `desktop/src/main/protocol.ts` 和 `docs/assets/`。

## Out of Scope

- 真实第三方 Provider 的账号额度、模型权限、网络质量或服务端 bug。
- API key 磁盘加密、系统密钥环、配置迁移和新的 Provider 管理界面。
- 与模型输出链路无关的视觉重构、主进程协议改动、Web 产品恢复或远端 master/PR 发布。

## Open Questions

- 当前不要求用户提供 API key。实现阶段先用本地可控 SSE 服务区分 Provider、sidecar 和 Renderer 根因；只有本地闭环仍无法解释用户现象时，才需要用户提供脱敏的 Provider 类型、endpoint 形态、模型名和“等待多久后仍无输出”等信息。
