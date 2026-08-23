# 桌面切换与 Web 删除：设计

## Packaging Pipeline

```text
Python source
  └─ PyInstaller onedir → dist/lion-sidecar/**

desktop source
  └─ electron-vite build → out/main + out/preload + out/renderer

electron-builder
  ├─ ASAR: Electron app assets
  ├─ extraResources/sidecar: PyInstaller output
  └─ NSIS: Windows x64 installer
```

构建脚本必须先构建/验证 sidecar，再运行 electron-builder。缺失 sidecar 是构建错误，不允许生成启动后才失败的安装包。

## API-only Server

- 保留 `/api/health`、受 capability 保护的 REST routes 与 `/ws/chat`。
- 删除 `_default_static_dir`、browser URL、webbrowser thread、StaticFiles mount 和公开页面含义。
- API app 的 Origin/Host 契约面向 `lion://app` 和 loopback，不扩大到任意浏览器 Origin。
- CLI/TUI/REPL 继续存在；只删除 Web GUI 入口。

## Removal Inventory

- `frontend/**` 旧源码与其 lock/build configuration。
- `lion_code/server/static/**` 构建产物。
- `scripts/build_frontend.py`、`scripts/verify_web_delivery.py` 及其测试/CI 引用。
- `pyproject.toml` 的 server static package-data。
- README Web 发布说明、CLI Web options 和只验证 Web 页面交付的测试。
- 旧 capability fragment/sessionStorage 代码随 frontend 一并删除。

任何共享协议代码必须已由 Child 2 迁移并有 desktop 测试后才能删除源文件。

## Release Verification

- 构建产物清单测试检查 sidecar executable、Renderer assets、license notices 和版本一致性。
- 安装态 E2E 不能从源码目录解析资源，测试时使用临时 workspace 和隔离的应用数据目录。
- 进程退出验证以 PID/进程句柄为准，不按进程名清理其他用户进程。

## Rollback

本 PR 是单一切换提交组。回滚该 PR 恢复旧 Web 入口和静态交付，同时保留已经合并的 Electron 宿主、Adapter 和新 Renderer；不保留双入口的长期分支逻辑。

