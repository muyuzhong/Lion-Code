# 设计：桌面客户端配置恢复与会话错误链路

## 1. 状态所有权与边界

- Python sidecar 继续拥有 Provider、凭证、模型和会话的 canonical 状态。
- Renderer 只持有设置页临时表单状态与脱敏后的 UI 投影；不把配置写入 localStorage，也不创建第二份 Provider 状态。
- Main/Preload 的 capability 与 sidecar 生命周期不变；配置读取复用现有 REST capability 认证。
- WebSocket wire event 不新增字段；未配置 API 继续使用既有 assistant error message 与 `agent_settled` 终态。

## 2. 配置写入/恢复数据流

```text
ProviderSettings
  ├─ GET /api/config/provider  ──> Python session/provider canonical state
  └─ POST /api/config/provider ─> Runtime 原子切换 -> config.json 持久化
                                      │
                         sidecar restart/build_session
                                      │
                         resolve_api_credentials -> ProviderState
```

### 2.1 读取契约

新增受 capability 保护的 `GET /api/config/provider`，返回 Provider、model、api key 和 active base URL。该接口只由设置页明确调用；不把 `api_key` 放入 `/api/status` 或普通历史/日志。

服务端从现有 `session.get_provider_config()` 形成响应，Provider 名称由 `use_openai` 映射为 `openai` / `anthropic`。写入仍由现有 POST 路由完成，保留空字段合并语义与失败回滚。

### 2.2 重启 Provider 选择

修复 `resolve_api_credentials` 的输出，使 OpenAI-compatible 且没有显式 `base_url` 时返回成熟的默认 OpenAI 地址。这样 `sidecar.build_session` 现有“由 api_base 选择 provider”的构造入口仍能保持正确 Provider，不增加第二个隐式 provider flag。

同时保留环境凭证覆盖 key/base URL、配置文件提供 model 的既有约定；更新四象限测试，特别覆盖保存的 OpenAI provider + 空 base URL。

## 3. 设置页交互

- `LionRestClient` 增加读取 Provider 配置的方法；adapter 负责把读取失败放入已有 metadata error，不让设置页静默显示空值。
- `ProviderSettings` 打开时加载 canonical Provider 配置，并以加载结果初始化 Provider/model/base URL/API key。
- API key 输入默认 `type=password`；眼睛按钮只改变当前 input 的 `type`，按钮有可访问名称和状态，关闭/重新打开组件自动回到 password。
- 保存期间禁用保存按钮；成功关闭，失败保留表单和错误。
- key 不出现在 React error、普通 metadata/status 组件和测试日志中；测试使用固定假 key 并避免快照泄漏。

## 4. 未配置 API 的真实终态

先用隔离 sidecar 集成测试确认当前 `AgentRuntime.chat` 的 assistant error、`SessionWebsocketBridge` 下发和 Renderer reducer 终态。若真实链路缺失事件，只修缺失层：优先保留 Python canonical assistant error，再补 bridge/adapter 的终态处理；不以 UI notice 作为并行错误协议。

验收要求同时观察：assistant error 文本可见、`isStreaming=false`、`agent_settled`/等价终态到达、下一次发送按钮可用。

## 5. 测试分层

- Python 单元：配置解析默认地址、读取/写入响应映射。
- Python 集成：真实 `create_app` + 隔离 session/provider，验证 GET/POST、sidecar 重建配置和无 API assistant error event 序列。
- Renderer 单元：读取配置注入表单、掩码/眼睛按钮、保存失败/成功状态。
- Electron Playwright：使用真实 Electron + Python sidecar 与隔离 `LION_SIDECAR_STATE_HOME`，至少验证无 API 发送的可见错误和保存后重启读取；不调用真实第三方 API。

## 6. 风险与回滚

- 暴露配置读取接口会扩大 Renderer 可见凭证范围，但仅在本机 capability 保护下、设置页明确调用；磁盘加密延后。
- OpenAI 默认地址修复可能改变无 base URL 的启动 Provider，但这是与保存 provider 语义一致的必要修复。
- 每个逻辑修改保留小范围提交与对应测试；回滚读取接口、默认地址和 UI 表单可以独立完成，不涉及 JSONL schema。
