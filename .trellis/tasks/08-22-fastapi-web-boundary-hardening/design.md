# FastAPI Web 前后端边界修复设计

## 1. 设计结论

不重写现有 React 视觉层，也不改 Core/Runtime。保留
`FastAPI -> LionCodingSession -> CodingSessionBackend`，重做接口边界的四个薄层：

```text
local browser
  -> process capability + Host/Origin gate
  -> typed REST / typed WebSocket actions
  -> one SessionWebsocketBridge owner
  -> LionCodingSession
  -> canonical Core events / JSONL history
```

父任务只拥有共同需求、子任务顺序和集成验收。实现由五个可独立回滚的子任务承载。

## 2. S1 本机访问安全边界

- `run_server` 固定绑定 `127.0.0.1`；删除 CLI `--host` 和公开 `host` 参数，不保留
  remote fallback。
- 每次启动用 `secrets.token_urlsafe()` 生成内存 capability token，不写配置或日志。
- 浏览器启动 URL 只把 token 放入 fragment；前端读入 `sessionStorage` 后清理地址栏。
  REST 使用 Bearer header，WebSocket 使用明确 subprotocol 传递，避免 query/access log。
- FastAPI 对受保护 `/api/*` 与 `/ws/chat` 统一做 constant-time token 比较；静态资源与
  health 可公开，但 status/cwd、配置、会话和 Agent 控制全部保护。
- 只允许 loopback Host；WebSocket 在 `accept()` 前校验 Origin。生产不需要宽泛 CORS；
  开发仅允许 Vite 的精确 loopback Origin，token 仍是必要条件。
- token 作为 `create_app`/测试可注入值，不进入 Runtime/Application port。

## 3. S2 WebSocket 协议与连接生命周期

### 上行

- 用 `Annotated[... , Field(discriminator="action")] + TypeAdapter` 解析客户端 action；
  所有模型 `extra="forbid"`，审批使用 strict bool，非法 action/choice/字段返回
  `protocol_error`，不得静默 continue。
- `SessionWebsocketBridge.handle_inbound_action` 接受已验证模型，不再使用 raw dict、
  `bool()` 或 `str()` 安全转换。

### 单连接所有权

- 一个 `LionCodingSession` 同时只允许一个 WebSocket owner；第二个连接在绑定 callback
  前以 policy close code 拒绝，避免 last-writer-wins。
- Bridge 提供幂等 `aclose()`：先拒绝 pending approval，再显式 `session.cancel()`，等待
  active run 收敛，取消/收集 notice task，最后只解除自己拥有的 callback。
- 断线后的新连接重新拉取 `/api/messages`，用 canonical history 替换 provisional UI；
  不尝试在 Web 层缓存或重放丢失增量。
- active task 是 Bridge 的运行闸门，避免 `session.is_running` 尚未置位时双 prompt。

### 下行与前端

- TypeScript 声明 canonical discriminated union，只读 `assistantMessageEvent`、
  `toolCallId`、`toolName`、`isError` 等 wire 字段，不保留 snake-case fallback。
- 工具结果按 ID 更新，并从 `AgentToolResult.content` 提取文本；`message_end` 做最终内容
  对账；Server/provider/protocol error 结束 streaming 并展示错误。
- 连接打开和重连均加载历史；关闭清空 stale approval。
- 以输入框作为最小控制面：Plan/其他 slash 输入发送 `command`，`/continue` 与
  `/compact` 映射现有专用 action。Hook 保留 steer/follow-up action 的类型化入口，
  本任务不增加复杂队列编辑 UI。

## 4. S3 Provider 设置一致性

- Web 先用 `session.provider_config()` 的当前完整快照合并局部请求；Provider 切换必须
  获得适用于目标协议的凭证，模型切换可复用同 Provider 凭证。
- 运行时切换仍只调用 `session.configure_provider`，保持 ProviderController 的原子构建
  与替换语义；配置文件使用临时文件 + `replace` 原子写入。
- Server 边界持有一次事务快照。任一阶段失败，恢复旧磁盘/运行时快照并返回结构化
  4xx/5xx；不得返回 500 后留下新 Runtime。
- 配置路径或 load/save callable 可注入测试；生产默认仍为 `~/.lion-code/config.json`。
- SettingsModal 在打开或 status/provider projection 更新时初始化草稿；空 API key 表示
  保留同 Provider 的现有 key，绝不把 UI 默认值写回。
- 模型选择保持 `(provider_name, model)` 对，不再丢弃 provider。

## 5. S4 workspace 会话隔离

- 只列出 cwd 缺失的 legacy session 或 resolve 后等于当前 cwd 的 session；明确属于其他
  cwd 的记录永不回退展示。
- resume 前在同一 server boundary 验证目标 id 位于允许列表；不存在或其他 cwd 均 404。
- 路径比较失败时只对该记录做规范化字符串比较，不扩大为全列表 fallback。

## 6. S5 服务生命周期与发布

- FastAPI lifespan 在 shutdown 恰好一次 `await session.aclose()`；WebSocket owner 先关闭。
- Vite 产物输出到 `lion_code/server/static`，以 package data 进入 wheel；运行时用
  `importlib.resources` 定位，不依赖仓库相对路径。
- 前端构建产物属于机械生成文件；源码改变后由明确命令重建并用 wheel 内容测试固定。
- 安装态 smoke test 验证 `/`、静态 asset、health 和带 token 的 status；缺产物时启动
  明确失败，不静默 API-only 运行。

## 7. 错误与状态契约

| 条件 | 结果 |
| --- | --- |
| 非 loopback Host / 非允许 Origin | 请求或握手前拒绝 |
| token 缺失/错误 | REST 401；WS policy close |
| 非法 JSON/action/strict field | `protocol_error`，无业务回调 |
| 第二 WebSocket | 拒绝，不改变现有 callback owner |
| active socket 断开 | deny approvals -> cancel run -> cleanup -> unbind |
| Provider 校验/构建/写盘失败 | 旧 Runtime 与旧配置保持一致 |
| 当前 cwd 无会话 | 空列表 |
| shutdown | Bridge 与 Session 各关闭一次 |

## 8. 兼容、依赖与回滚

- 不保留未认证协议、snake-case Web 别名、远程 `--host` 或 source-tree static fallback。
- 不新增生产依赖：认证使用 stdlib，校验使用既有 Pydantic/FastAPI。
- 前端测试使用 Vitest + React Testing Library + jsdom，覆盖纯 event reducer、认证 token
  导入与 Hook 的连接/重连 effect；只增加开发依赖，不进入生产 bundle。
- 子任务依赖顺序：S1 -> S2 -> S3 -> S4 -> S5。依赖来自 token/API client 与最终
  package smoke test，不由父子目录隐式表达。
- 每个子任务单独提交并可回滚。当前 Web 基线未在 master；发布 PR 前先建立干净基线，
  不重写或丢弃当前用户分支历史。
