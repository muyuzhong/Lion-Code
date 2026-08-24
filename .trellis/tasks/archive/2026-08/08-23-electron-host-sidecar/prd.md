# Electron 宿主与 Python sidecar

## Goal

建立 Windows x64 Electron 产品宿主、安全 Main/Preload/Renderer 边界和可诊断、可回收的 Python sidecar 生命周期，为后续聊天 Runtime 与视觉重构提供稳定运行底座。

## Dependencies

- 无桌面子任务依赖。
- 必须从干净的 `master` 派生独立分支，不在当前 memory-system 工作树上实现。
- 本任务只建立宿主与最小连接状态页；不实现最终聊天 UI。

## Requirements

- 新建独立 `desktop/` Node package，使用 Electron、electron-vite、electron-builder、React 与 TypeScript。
- Main 注册受限 `lion://app` 自定义协议并创建安全 `BrowserWindow`。
- Preload 只暴露工作区选择、连接 bootstrap 和应用版本等允许列表能力。
- Main 选择绝对 workspace，启动开发态 Python 模块或打包态 PyInstaller `onedir` sidecar。
- Python 使用动态 loopback 端口并输出严格 ready JSON；capability 只通过父子 pipe 和受限 IPC 进入 Renderer。
- Main 对 ready 超时、非法记录、启动失败、意外退出和正常关闭分别建模。
- Renderer 提供选择工作区、连接中、连接成功和诊断错误四种最小状态。
- 关闭窗口或切换 workspace 后不遗留由本窗口创建的 Python 子进程。
- Python sidecar 仍通过现有 Composition Root 构造 Full 产品；不得把 Electron 概念注入 Runtime/Capability。

## Acceptance Criteria

- [ ] `npm run dev` 能启动安全 Electron 窗口并选择 Windows 目录。
- [ ] 窗口加载 `lion://app`，不使用 `file://` 或远程页面。
- [ ] `nodeIntegration=false`、`contextIsolation=true`、`sandbox=true` 有配置测试锁定。
- [ ] Preload 不暴露原始 IPC、文件系统、shell 或 child_process。
- [ ] sidecar 绑定 `127.0.0.1` 随机端口并成功返回 endpoint/capability bootstrap。
- [ ] capability 不出现在 argv、URL、sessionStorage、本地配置和普通日志。
- [ ] 非法/重复 ready、启动超时和异常退出产生结构化诊断状态。
- [ ] Electron 退出后对创建的 sidecar 做有界优雅关闭和精确兜底终止。
- [ ] Python sidecar 定向测试、Electron Main/Preload 单测和最小 Electron E2E 通过。

## Out of Scope

- assistant-ui 消息映射和最终聊天页面。
- Windows 安装包、自动更新与签名。
- 多 workspace 同时运行。
- macOS/Linux 进程差异。

