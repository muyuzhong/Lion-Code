# Electron 桌面客户端重构：总体设计

## Architecture

```text
Electron Main
├─ WindowController
├─ WorkspaceController
├─ SidecarController
└─ typed IPC handlers
        │
Electron Preload ── narrow DesktopBridge
        │
Electron Renderer
├─ LionAssistantRuntimeAdapter
├─ assistant-ui primitives
└─ Lion design system
        │ REST / WebSocket
Python API-only sidecar
└─ LionCodingSession → CodingSessionBackendAdapter → MetaAgent
```

Electron 是 Interfaces 层的新产品宿主，不进入 Kernel、Agent Runtime、Capability 或 Composition。Python 继续通过 `build_full_coding_backend()` 构造完整产品，桌面宿主只管理该产品进程的外部生命周期。

## Repository Shape

```text
desktop/
├─ package.json
├─ electron.vite.config.ts
├─ electron-builder.yml
└─ src/
   ├─ main/
   ├─ preload/
   ├─ renderer/
   └─ shared/

lion_code/server/
├─ app.py          # API-only FastAPI application
├─ bridge.py       # WS/Application bridge
├─ models.py       # strict wire/REST models
└─ sidecar.py      # desktop-owned process entrypoint
```

旧 `frontend/` 中可复用的协议代码在子任务 2 迁移到 `desktop/src/shared`；旧展示代码不迁移。子任务 4 删除旧目录和静态产物。

## State Ownership

| State | Owner | Projection/consumer |
| --- | --- | --- |
| window, workspace selection, sidecar process | Electron Main | Preload/Renderer read-only bootstrap |
| active conversation and session JSONL | Python Application/SessionRuntime | REST/WS → Adapter |
| Provider configuration and Thinking | `ProviderController` | Application commands → Renderer projection |
| streaming UI projection | `LionAssistantRuntimeAdapter` | assistant-ui |
| theme, composer draft, transient panels | Renderer | local UI only |

禁止 Main 或 Renderer 建立第二份 canonical message/session store。最近工作区是桌面偏好，不是 Lion Session 状态。

## Sidecar Bootstrap Contract

1. Main 选择绝对 workspace 路径并启动打包后的 Windows x64 sidecar。
2. workspace 路径可作为非敏感启动参数；端口传 `0` 由 OS 分配。
3. Python 生成 capability，绑定 `127.0.0.1`，在 stdout 输出一条严格 JSON ready 记录：`{"type":"ready","port":N,"capability":"..."}`。
4. stdout 在 ready 前只允许协议记录；诊断和日志写 stderr。Main 对记录做严格解析、超时和进程身份绑定。
5. Main 通过一次受限 IPC invoke 将 endpoint/capability 提供给已验证 sender 的 Renderer；不写 URL fragment、sessionStorage、命令行或磁盘。
6. Renderer 直接使用 REST/WS；高频 Token 不经过 Electron IPC。
7. 窗口退出或切换 workspace 时，Main 先请求优雅关闭，再在有界超时后终止该确切子进程。

## Renderer Loading and Security

- Main 注册标准、secure、支持 fetch 的 `lion://app` 自定义协议，只映射 Renderer 构建目录内的规范化路径。
- `BrowserWindow` 使用 `nodeIntegration: false`、`contextIsolation: true`、`sandbox: true`。
- 设置收敛 CSP；阻止任意导航、新窗口、未知外链和未声明权限。
- Preload 不暴露通用 IPC channel；每个方法固定 channel、参数 schema 和返回类型。
- Python API 继续验证 loopback Host/Origin 与 bearer/subprotocol capability；桌面 Origin 使用固定 `lion://app` 允许值。

## Chat Runtime Contract

- Lion REST history 是 canonical 已完成历史。
- Lion WS event 是活动 run 的 canonical 流式输入。
- `LionAssistantRuntimeAdapter` 复用并收敛现有 decode/reducer 规则，再输出 assistant-ui message/thread 状态。
- assistant-ui 的 composer、thread 与 tool UI 触发 Adapter 动作；Adapter 将动作编码为现有 `prompt`、`steer`、`follow_up`、`cancel`、`continue`、`compact`、确认和 Plan 审批消息。
- assistant-ui 不拥有后端重试、会话持久化或 Provider 配置策略。

## Distribution

- Python sidecar 使用 PyInstaller `onedir` 冻结；避免 `onefile` 每次启动解包和扫描开销。
- electron-builder 通过 `extraResources` 将 sidecar 目录放在 `process.resourcesPath` 下。
- 第一版生成未签名的 Windows x64 NSIS 测试安装包；签名与自动更新明确延期。

## Rollout and Rollback

- 子任务 1–3 在旧 Web 入口仍存在时分别验证，但不引入运行时 fallback。
- 子任务 4 是唯一切换点：只有桌面 E2E 和安装态烟测通过后才删除 Web 入口。
- 每个子任务对应独立 PR；回滚任一前置 PR不会改变 Python canonical session 文件。
- 子任务 4 的回滚点是其删除提交；回滚后恢复旧 Web 产品，但不影响已经合并的底层宿主/Adapter代码。

## Trade-offs

- Electron 增加安装体积，但换取成熟的 Chromium、Node 主进程和 Windows 桌面生态。
- 保留 REST/WS 而不改成全 IPC，避免重复协议并保持 Python Application 边界。
- assistant-ui 减少滚动、线程、Composer 和可访问性自研成本，但要求一个明确的 Lion Adapter。
- Windows-only 降低首版发布矩阵；跨平台不能以条件分支形式提前进入本任务。

