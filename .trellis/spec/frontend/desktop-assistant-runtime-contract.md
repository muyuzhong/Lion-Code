# 桌面 assistant-ui Runtime 契约

## 1. Scope / Trigger

触碰 `desktop/src/shared/chat.ts`、`desktop/src/renderer/src/backend.ts`、
`lionRuntime.ts` 或 assistant-ui Provider 时必须遵守本契约。它约束 Python canonical
Session 与 Renderer 活动 run 投影之间的跨层边界；Provider、Session 和 Skill 的可写状态不属于 Runtime。
工具结果需要在 WorkPanel 打开时，也触发本契约：资源只能作为可选引用投影，文件读取仍由
Python capability-protected REST 端点拥有。

## 2. Signatures

```typescript
interface BackendBootstrap {
  endpoint: { baseUrl: string; capability: string };
  fetch: typeof globalThis.fetch;
  createWebSocket(url: string, protocols: string[]): WebSocketPort;
  scheduleReconnect(callback: () => void, delayMs: number): number;
  cancelReconnect(id: number): void;
}

type ClientAction =
  | { action: "prompt" | "steer" | "follow_up"; prompt: string }
  | { action: "continue" | "compact" | "cancel" }
  | { action: "confirm_response"; requestId: string; approved: boolean }
  | { action: "plan_approval_response"; requestId: string; choice: PlanApprovalChoice; feedback?: string };

type OpenableResourceRef = { path: string; expectedSize?: number | null };
type OpenableResourceResponse = {
  status: "ready" | "missing" | "outside_workspace" | "not_file" | "too_large" |
    "binary" | "encoding_error" | "changed" | "unreadable";
  path: string; name: string; format: "text" | "markdown" | "diff";
  size: number | null; modifiedAtNs: string | null;
  content: string | null; message: string | null;
};

LionRestClient.openResource(ref, expectedMtimeNs?) -> Promise<OpenableResourceResponse>
LionAssistantRuntimeAdapter.openResource(ref) -> Promise<void>
LionAssistantRuntimeAdapter.reloadOpenedResource() -> Promise<void>
```

REST 使用 `GET /api/messages` 替换历史快照，切换会话使用
`POST /api/sessions/resume` 的 `{ "session_id": string }`。WebSocket 固定连接
`/ws/chat`，subprotocol 为 `lion-code` 与 `lion-code-capability.<capability>`。

## 3. Contracts

- `LionAssistantRuntimeAdapter` 是 Renderer 聊天投影的唯一 owner；assistant-ui External Store
  只订阅该投影，不建立第二套 React 消息 store。
- REST history 是已完成消息的 canonical bootstrap；WS 只折叠当前 run。历史替换清空 queue、
  notice、metrics、审批和临时消息。
- wire 只接受后端 camelCase alias，例如 `toolCallId`、`assistantMessageEvent`、
  `followUp`、`requestId`、`willRetry`；禁止 snake_case、fallback 或宽松兼容。
- `GET /api/status` 的 `api_configured` 必须与
  `provider_blocker_code` 成对解码：就绪时为 `true/null`，阻塞时为
  `false/"provider_configuration_required"`；缺失、未知或不一致的 code
  必须在 REST metadata 边界拒绝。
- `queue_update` 全量替换队列；user `message_start` 按文本消费，steering 优先且一次只移除一项。
- Tool start/update/end 只按 `toolCallId` 配对，允许结束事件乱序；不得按 args 形状推断工具类型。
- `tool_execution_end` 的 `details.persisted_path` 优先于白名单文件工具的 `file_path`；
  只有 `read_file`、`write_file`、`edit_file` 可以从参数产生资源引用，shell/search 不得猜路径。
- `OpenableResourceResponse` 的 `content` 只有 `status=ready` 时可以是字符串；其他状态必须为
  `null`。Renderer 只展示当前 `openedResource`，不直接使用 `fs`、Node 或 raw IPC。
- 资源读取以当前 session 的 workspace 或固定 `~/.lion-code/tool-results` 为根，后端限制 256 KiB，
  并在读取前后校验文件属性；修改或请求乱序不能覆盖当前资源。
- assistant-ui 仅 assistant message 可携带 `status`；user message 不投影该字段。
- Streamdown 只渲染 assistant 文本 part，不参与消息、工具或执行状态所有权。

## 4. Validation & Error Matrix

| 条件 | 必须行为 |
| --- | --- |
| capability 不符合 `[A-Za-z0-9_-]{32,128}` | 不建立 WS，进入显式 transport error |
| REST 非 2xx 或 history schema 非法 | 不连接 WS，保留显式 error |
| status 缺少/未知/不一致的 `provider_blocker_code` | 拒绝 metadata，暴露显式 protocol error |
| WS JSON/schema/alias 非法 | 关闭 socket，终止流，清除 pending approval，保持 protocol error |
| 普通断连 | 终止流并清审批，2 秒后重连；不清 queue |
| 重连或 session switch | 先拉 canonical history，成功后才连接 WS |
| 旧 history/reconnect 异步结果晚到 | 用 request id 与 connection generation 丢弃，不得覆盖当前 Session |
| confirm/plan response 发送失败 | 不清本地请求，禁止静默批准 |
| 资源路径越界、不是普通文件、过大、二进制或非 UTF-8 | REST 返回 typed status 且 `content=null`，WorkPanel 显示原因 |
| 已打开资源的 size/mtime 改变 | 返回 `changed`，不得把读取内容当作稳定快照 |
| 资源打开请求晚于新的打开/历史替换/会话切换 | 旧 Promise 结果被 request/generation 丢弃 |

## 5. Good / Base / Bad Cases

- Good：切换 Session 时取消 pending reconnect，递增 generation，resume 与 history 均成功后再连 WS。
- Base：启动时 history 为空，仍以空 Thread 建立 WS 并等待新 run。
- Bad：REST 恢复期间让旧 reconnect 回调提前连接，或协议错误后保留 socket/pending approval。
- Good：工具完成事件和 REST 历史都投影为同一个资源引用，点击后 WorkPanel 通过受保护 REST 读取。
- Base：资源不存在时仍显示文件名和结构化缺失原因，不显示空白成功内容。
- Bad：把 `persisted_path` 原样写进第二个 Renderer 文件系统读取器，或让过期响应覆盖新文件。

## 6. Tests Required

- `chatProtocol.test.ts`：严格 camelCase 解码、blocks user 出队、同文本 steering 优先、
  retry/compaction notice 终态、reasoning/tool 计时、乱序 `toolCallId`、时长进位边界。
- `assistantRuntime.test.ts`：REST bootstrap、全部 ClientAction、session switch/reconnect generation、
  protocol error 与 disconnect fail-closed、assistant-ui parts/status 投影。
- 资源测试必须断言：合法/非法 openable 解码、REST capability 与响应 guard、`details` 投影、
  request generation/session reset、非 ready 状态不带内容，以及 WorkPanel 只读展示和 reload。
- `chat-protocol.spec.ts`：真实 Electron Renderer 中完成 REST history → WS prompt →
  单条流式 assistant message 的端到端路径。
- 变更后运行 `npm run typecheck`、`npm test`、`npm run build` 与对应 Playwright project。

## 7. Wrong vs Correct

**Wrong**：把 WS 事件直接写入组件 `useState`，同时让 assistant-ui 维护另一份 Thread；重连时先连 WS
再异步覆盖 history；协议错误只显示 toast 但继续保留连接和审批。

**Correct**：所有 REST/WS 输入先进入单一 `LionAssistantRuntimeAdapter`，重连先完成 canonical
history 且核对 generation，再连接 WS；任何协议错误立即关闭 transport 并 fail closed。

**Wrong**：Renderer 收到工具返回的绝对路径后直接调用 Node `fs.readFile`，或把 shell 输出中的任意
路径都注册成资源。

**Correct**：Python 只投影 `persisted_path` 或明确文件工具路径，端点每次重新校验允许根、普通文件、
大小、编码和前后属性；Renderer 只消费严格响应并在 WorkPanel 只读渲染。
