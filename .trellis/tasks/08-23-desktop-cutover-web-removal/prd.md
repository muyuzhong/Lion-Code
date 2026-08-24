# 桌面切换与 Web 删除

## Goal

将已经通过验收的 Electron 客户端切换为 Lion 唯一 GUI，完成 Windows x64 打包链，并彻底删除旧 Web 产品入口、静态托管、旧聊天 UI 与相关交付资产。

## Dependencies

- 强依赖 `08-23-electron-host-sidecar`、`08-23-assistant-ui-protocol-adapter`、`08-23-lion-desktop-chat-experience` 全部合并且 CI 通过。
- 必须先在最新 `master` 上完成桌面开发态 E2E；依赖不满足时不得提前删除 Web。
- 本任务是唯一产品切换点，不与前置任务并行合并。

## Requirements

- 使用 PyInstaller `onedir` 构建 Windows x64 Python sidecar，并以 electron-builder `extraResources` 纳入安装资源。
- 生成 Windows x64 NSIS 测试安装包；首版不签名、不自动更新。
- 打包态必须从 `process.resourcesPath` 启动 sidecar，不依赖系统 Python、源码 checkout 或全局 Node。
- 删除 CLI `--web`、`--port`、`--no-browser` 及 Web 专用启动分支。
- FastAPI `create_app` 变为 API-only，不再定位或挂载静态前端。
- 删除 `lion_code/server/static`、旧 `frontend/`、前端构建/验证脚本、Python package data 和 Web-only 文档测试。
- 保留 REST/WS API、严格模型、本机鉴权与 Server Bridge，供 Electron Renderer 使用。
- 更新 README、目录结构、安装/开发命令、质量基线和发布物验证。
- 不保留浏览器 fallback、API-only headless Web 产品开关或兼容 CLI alias。

## Acceptance Criteria

- [ ] 在无 Python/Node 开发环境的干净 Windows 10/11 x64 机器上可安装并启动。
- [ ] 安装态能选择 workspace、配置 Provider、完成流式对话、审批、会话恢复和正常退出。
- [ ] 安装目录包含预期 sidecar 资源且不包含 Python 源码、旧 Web 静态包或开发依赖。
- [ ] 关闭/卸载前应用退出不遗留 sidecar 进程。
- [ ] `lion-code --web` 及 Web-only 参数明确不存在，不提供兼容提示层。
- [ ] FastAPI 不再 mount `/` 静态站点，wheel/sdist 不再包含 `server/static`。
- [ ] 仓库不存在旧 `frontend/`、`build_frontend.py`、`verify_web_delivery.py` 或孤儿 bundle 引用。
- [ ] Python 全套质量门禁、desktop 测试/build/E2E 和安装态烟测通过。

## Out of Scope

- Windows 代码签名、SmartScreen reputation、自动更新和 Microsoft Store。
- macOS/Linux 安装包。
- 安装器 UI 品牌精修之外的新产品功能。

