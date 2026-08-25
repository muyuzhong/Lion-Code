# 修复桌面客户端配置恢复与会话错误链路

## Goal

让 Electron preview 与后续安装包中的桌面客户端具备可验证的 Provider 配置闭环：用户保存的配置能够在重新打开设置或重启 sidecar 后恢复；API key 默认以密文显示并可由眼睛按钮临时查看；已配置会话可以正常进入运行链路；未配置 API 时必须显示明确的终止错误而不是停在运行中。

## Confirmed Facts

- 上一个提交 `d243ef82` 只让 Provider 写入不再等待辅助 metadata 刷新；用户已经在重新 `build` 后通过 `npm run preview` 复测，保存请求虽不再卡住，但设置重新打开没有上次的配置，会话仍不能正常进行。
- `desktop/src/renderer/src/WorkspaceShell.tsx` 当前用空字符串初始化 API key，仅显示“已配置；留空保持不变”占位文本；设置页没有读取已保存 API key 的接口，也没有可切换可见性的按钮。
- `desktop/src/renderer/src/backend.ts` 当前只有 Provider 配置 POST；`lion_code/server/app.py` 当前只有 `/api/config/provider` 写入路由，没有专门的配置读取契约。
- `lion_code/sidecar.py::build_session` 根据 `resolve_api_credentials` 返回的 `api_base` 是否为空来选择 Provider。保存的 OpenAI 配置在 `base_url` 为空时可能返回 `use_openai=true` 但 `api_base=None`，随后初始 Runtime 会按 Anthropic 构造，造成重启后的 Provider/key 不匹配。
- `lion_code/runtime/agent.py::chat` 已有未配置 API 的 assistant error 事件实现；现有桌面回归主要注入 fake WebSocket，尚未证明真实 preview sidecar 的事件、终态和 UI 投影完整闭环。
- 磁盘上的凭证加密不在本任务范围；现有本地 JSON 写入方式保持不变。API key 的“密文”仅指设置界面的默认显示形态。

## Requirements

### R1. Provider 配置可恢复并可回显

- 保存后重新打开设置页，Provider、模型、API 地址和已保存 API key 均显示上次值。
- API key 默认显示为密码掩码；眼睛按钮可在当前设置页临时切换明文/掩码，关闭设置页后再次默认掩码。
- API key 只通过受本机 capability 保护的明确配置读取/写入路径交付给 Renderer，不加入普通 `/api/status`、会话列表、日志或错误文本。
- 重启 sidecar 后，保存的 Provider、模型、key、base URL 仍构造出相同的 Provider；OpenAI 默认地址为空时也必须保持 OpenAI-compatible，不得降级为 Anthropic。

### R2. 已配置会话可运行

- 保存有效 Provider 配置后，发送非空消息能够进入真实 sidecar 的 WebSocket 运行链路，并最终收到 assistant 完成消息或可见的 Provider 错误。
- 保存、重启、重新连接的过程中不得遗留永久 `isStreaming`/`is_running` 状态。
- 保存失败时设置页保持打开并显示错误；只有 canonical Provider 写入和持久化成功后才关闭。

### R3. 未配置 API 的错误可见且终止

- 在真实 preview sidecar 未配置 API 时发送消息，聊天区域显示明确的 assistant 错误或等价错误提示。
- 该轮运行必须收到终态，发送框恢复可用；不能只发送被 Renderer 丢弃的 notice，也不能一直显示“运行中”。
- 已有正常流式消息和 assistant-ui 的错误投影行为保持不变。

### R4. 真实链路回归

- 回归测试至少覆盖：配置写入→读取、sidecar 重建后的 Provider 选择、设置页回显/眼睛按钮、未配置 API 的真实 WebSocket 终态。
- 测试使用隔离的 state home，不读取或修改开发者真实 `~/.lion-code` 配置。

## Acceptance Criteria

- [ ] 通过受保护的 Provider 配置读取契约，设置页重新打开能看到已保存的 Provider、模型、base URL 和掩码 key；点击眼睛按钮能查看/隐藏 key。
- [ ] 写入 OpenAI 配置且 base URL 留空后重启 sidecar，`/api/status`、Provider 配置读取和首次 prompt 使用 OpenAI-compatible 默认地址；不会按 Anthropic 初始化。
- [ ] 未配置 API 时真实 preview WebSocket 收到 assistant error/终态，Renderer 显示错误，`isStreaming` 最终为 false。
- [ ] 已配置路径至少由隔离 sidecar/server 集成测试证明 POST、重建读取和运行终态闭环；不得以 fake adapter 单测作为唯一证据。
- [ ] `npm test`、`npm run typecheck`、相关 Playwright/集成测试以及 Python 定向质量检查通过；全量测试中的既有基线噪声单独记录。
- [ ] 不修改磁盘凭证格式或实现磁盘加密；不触碰用户已有的 `desktop/src/main/protocol.ts` 和 `docs/assets/` 改动。

## Out of Scope

- API key 磁盘加密、系统密钥环集成或配置迁移。
- 真实第三方 Provider 网络可用性、账号额度和模型权限保证；测试只验证本地配置/传输/终态闭环。
- 与本问题无关的视觉重构、主进程协议改动和远端 master/PR 发布。

## Open Questions

无。用户已确认只要求 UI 密文显示，不要求磁盘加密；配置读取 API 的凭证暴露范围限定为本机 capability 保护的显式设置路径。
