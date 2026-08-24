# Electron 桌面客户端重构

## Goal

将 Lion 从“Python Web 服务附带浏览器页面”重构为 Windows 原生桌面产品，优先建立可靠、紧凑、具有 Lion 自有视觉语言的聊天体验，同时保持 Agent、Session、Tool Runtime、Provider 与持久化契约不变。

## Background

- 当前 `LionCodingSession` 已提供前端可消费的 Application 门面，覆盖会话、流式事件、Provider、Thinking、Skill、审批、Steer、Follow-up 与取消。
- 当前 FastAPI/WS 控制面绑定一个 workspace 和一个 `LionCodingSession`，已具备本机 capability 鉴权与单连接所有权。
- 当前 React 主路径仍由 `components/chat/*` 与自研 hook 组织；`assistant-ui` 已安装但没有成为唯一聊天 Runtime。
- 用户已明确不保留 `lion-code --web`，旧 Web UI、静态托管和兼容 fallback 均应删除。

## Requirements

### R1. 唯一桌面产品

- Electron 是唯一 GUI 产品入口。
- 第一版仅支持 Windows 10/11 x64。
- Python 作为由 Electron 管理的本机 sidecar 运行，不感知 Electron UI。

### R2. 桌面安全边界

- Electron Main 拥有窗口、工作区、sidecar、动态端口和 capability 生命周期。
- Renderer 禁用 Node integration，启用 context isolation 与 sandbox。
- Preload 只暴露经过类型约束的最小原生能力，不暴露 `ipcRenderer`、文件系统或任意进程执行。
- 本地页面使用受限自定义协议加载，不使用 `file://`。

### R3. 单一聊天 Runtime

- `assistant-ui` 是唯一聊天交互框架。
- `LionAssistantRuntimeAdapter` 将 Lion 的 canonical REST/WS 消息与动作映射到 assistant-ui。
- 现有协议 reducer 中已经验证的流式消息、工具、审批、队列、重试和压缩语义必须保留。
- 不引入 Vercel AI SDK 作为第二套消息或执行状态源。

### R4. 首版桌面聊天体验

- 支持工作区选择与最近工作区、会话列表、新建和恢复。
- 支持流式 Markdown、Reasoning、Tool Call、错误、Permission 与 Plan 审批。
- 支持 Steer、Follow-up、Cancel 与服务端队列快照语义。
- 支持 Provider、模型、Thinking 基础设置与深浅色主题。
- sidecar 未就绪、启动失败或运行中退出时，Renderer 必须呈现可诊断状态。

### R5. 视觉方向

- 参考 Codex 的布局逻辑、信息密度和流式交互节奏，不做像素复刻。
- Lion 自行定义色彩、排版、图标、空状态、工具卡片和状态文案。
- 界面围绕任务进展与工具活动组织，不退化为气泡式聊天列表。

### R6. 状态所有权保持不变

- Python Application 继续拥有会话、Provider、Agent 执行和持久化。
- `ProviderController` 继续是 Provider 可写状态的唯一 Owner。
- Adapter 只投影和转发，不复制可写 Provider/Session 状态。
- Renderer 只拥有主题、面板开关和草稿等瞬态 UI 状态。

### R7. Web 产品删除

- 最终删除 `--web`、FastAPI 静态页面挂载、`lion_code/server/static`、旧前端构建/交付脚本和旧聊天 UI。
- 删除发生在新桌面主链路达到验收标准之后，但同一最终产品中不保留 fallback。

### R8. 可独立交付

- 本任务作为父任务管理四个独立子交付；父子关系不代替依赖声明。
- 每个子交付必须有单独的状态所有权、验收矩阵、回滚点和 PR。

## Deliverable Map

1. `08-23-electron-host-sidecar`：Electron 宿主、安全边界与 sidecar 生命周期；无桌面子任务依赖。
2. `08-23-assistant-ui-protocol-adapter`：Lion 协议到 assistant-ui 的单一 Runtime；依赖子任务 1 提供 Renderer/Preload 基础，但协议单测可先行。
3. `08-23-lion-desktop-chat-experience`：全新聊天界面与 Lion 设计系统；依赖子任务 2 的稳定 Runtime Adapter。
4. `08-23-desktop-cutover-web-removal`：Windows 打包、切换与旧 Web 删除；依赖子任务 1–3 全部通过验收。

## Acceptance Criteria

- [ ] Windows x64 安装态应用可以选择工作区、启动 sidecar 并进入聊天界面。
- [ ] Renderer 无 Node.js 访问能力，Preload API 有显式类型、允许列表和 sender 校验。
- [ ] sidecar 只监听 loopback 动态端口，capability 不出现在 URL、命令行或持久化文件中。
- [ ] 流式消息、Reasoning、Tool、审批、队列、Steer、Follow-up 与 Cancel 行为符合既有协议契约。
- [ ] 会话可以新建、恢复并继续由 Python canonical JSONL 持久化。
- [ ] Provider/Thinking 更新仍通过 Application 门面进入 `ProviderController`。
- [ ] sidecar 启动失败和异常退出都有可诊断 UI，关闭 Electron 后不遗留子进程。
- [ ] 旧 Web 产品入口、静态托管、旧聊天 UI 和交付脚本全部删除。
- [ ] 四个子任务分别通过其定向测试，最终集成通过 Python、前端、Electron E2E 与 Windows 打包烟测。

## Out of Scope

- macOS、Linux、ARM64。
- 多工作区并行与后台任务编排。
- 图片/文件附件、PTY 终端、文件树、Diff 审阅。
- 轨迹瀑布和完整性能指标。
- 自动更新、代码签名、商店发布。

