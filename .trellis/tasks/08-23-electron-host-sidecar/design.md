# Electron 宿主与 Python sidecar：设计

## Ownership

- `WindowController`：创建窗口、限制导航/新窗口/权限并加载 Renderer。
- `WorkspaceController`：目录选择和最近工作区桌面偏好。
- `SidecarController`：单一子进程句柄、启动状态、ready timeout、优雅关闭与兜底终止。
- Python `sidecar.py`：解析 workspace、构造 `LionCodingSession`、生成 token、绑定 loopback、输出 ready。
- Renderer：只消费连接状态，不拥有进程句柄或凭证持久化。

## Ready Protocol

stdout 第一条非空记录必须是 UTF-8 单行 JSON：

```json
{"type":"ready","version":1,"port":49152,"capability":"<url-safe-token>"}
```

- schema 拒绝额外字段、非 loopback 端口、错误版本和非法 token。
- ready 前 stderr 可收集诊断；stdout 的协议错误直接判启动失败。
- ready 后 capability 只保存在 Main 内存，并通过 sender-checked `desktop:get-backend` 返回当前窗口。
- 子进程退出时 Main 清除 bootstrap，Renderer 收到状态变化后停止重连。

## Security

- `protocol.handle("lion", ...)` 对 URL 解码、规范化并验证最终绝对路径仍位于 Renderer dist 根目录。
- CSP 默认 `default-src 'self'`，只为 loopback API/WS 和必要内联样式策略开最小口子。
- `will-navigate`、`setWindowOpenHandler` 与 session permission handler 默认拒绝；允许外链必须使用固定 HTTPS allowlist 和受检 `shell.openExternal`。
- IPC handler 校验 `event.senderFrame.url` 属于 `lion://app` 且窗口身份匹配。

## Development and Packaged Modes

- 开发态由 Main 启动当前 Python 解释器的内部 sidecar module。
- 打包态从 `process.resourcesPath/sidecar/` 启动冻结 executable。
- 两种模式共享同一 ready/stop 合约；不得用生产 fallback 掩盖打包缺失。

## Error Model

Renderer bootstrap 是判别联合：`idle | starting | ready | failed | exited`。错误包含稳定 code 与安全 message；stderr 尾部只在诊断视图显示并经过秘密净化，不进入聊天历史。

## Rollback

回滚本 PR 即删除 `desktop/` 宿主骨架和 Python sidecar 入口；现有 Web/TUI/CLI 与 Session 文件保持不变。

