# PI-Desktop UI 移植

## Goal

将 Lion 当前 Cherry Studio 风格的 Electron Renderer 替换为以 PI-Desktop 为主要来源的成熟编码 Agent 桌面界面，同时保持现有聊天行为、状态所有权、安全边界和打包链路不变。用户获得 PI-Desktop 式的项目/会话导航、紧凑消息流、工具活动、审批与底部 Composer，而不是重新实现一套前端 Runtime。

## Background

- 当前桌面产品已经完成 Electron 宿主、Python sidecar、assistant-ui External Store、REST/WS 协议适配与 Windows x64 打包。
- 当前展示入口集中在 `WorkspaceShell.tsx`、`ChatThread.tsx` 与 `styles.css`；`assistantRuntime.tsx`、`lionRuntime.ts`、`backend.ts` 和 `desktop/src/shared/chat.ts` 拥有行为与协议，不属于本次 UI 移植范围。
- PI-Desktop 在 commit `e56a3ed179a728723bde050f941e896922d67590` 提供 React 19、electron-vite、Zustand 和 CSS 驱动的编码 Agent UI。其视觉组件与 Lion 高度匹配，但组件直接依赖 PI 的 `app-store`、shared types、插件和 Host API，不能把整个 Renderer 原样接入。
- 当前工作树存在用户未提交的 `desktop/src/renderer/src/styles.css` 修改。本任务必须在独立干净工作树中实现，不覆盖、暂存或提交该修改。

## Requirements

### R1. 只替换展示层

- 保留 `LionAssistantRuntimeAdapter` 作为唯一聊天投影 Owner。
- 保留现有 REST/WS、严格 wire 解码、重连、会话、队列、审批、Provider 和 sidecar 行为。
- 不引入 PI-Desktop 的 Zustand store、Rust Host、Agent Runtime、Plugin SDK、持久化或 API client。
- 不建立第二套消息、会话、Provider、审批或执行状态。

### R2. 忠实复现 PI-Desktop UI

- 以固定 commit 的实际源码和用户提供的 PI-Desktop 截图为像素级方向，复现黑色左侧项目/会话树、深灰中央消息区、46px 顶栏、浮动底部 Composer 和右侧工作面板。
- 直接采用上游深色 Token、三栏比例、主要间距、边框、圆角与文字层级，不再做 Lion 暖色或营销化再设计。
- 保留 Lion 品牌、产品名称和文案，不复制 PI 品牌、Logo、Marketplace 或更新界面。
- 同一套语义 Token 支持深色与浅色主题；深色为默认视觉验收基准。
- 图标优先使用成熟图标库或已有 assistant-ui primitive，不手写大批 SVG。

### R3. 现有能力完整呈现

- 工作区、会话列表、新建/恢复、Skills、Provider/模型/Thinking 设置继续可用。
- 流式 Markdown、Reasoning、Tool、错误、重试/压缩状态继续可见。
- Permission、Plan 审批、Steer、Follow-up、Cancel 和队列状态继续可操作。
- 空会话、连接中、断线重连、协议错误和 sidecar 失败状态具有明确界面。

### R4. 最小改动面

- 主要修改限于 `desktop/src/renderer/src/` 的展示组件、样式与对应 Renderer 测试。
- 除非现有接口无法表达展示需要，不修改 `assistantRuntime.tsx`、`lionRuntime.ts`、`backend.ts`、`desktop/src/shared/chat.ts`、Main、Preload 或 Python。
- 不引入 Tailwind、Zustand 或 PI workspace packages；允许增加一个通用图标依赖，但不得引入第二套组件框架或状态框架。
- 以小型 Lion-owned 展示组件适配 assistant-ui primitives，不复制 PI 的 1,000 行级状态耦合组件。

### R5. 可访问性与窗口适配

- 键盘焦点、Escape 安全动作、ARIA label、状态文本和 reduced-motion 契约保持不变。
- 1280x720 与 2560x1440 下无 document 级横向溢出，侧栏、Composer 和审批操作始终可达。
- 会话、工具和长 Markdown 内容有稳定滚动边界，不产生双滚动或遮挡 Composer。

## Acceptance Criteria

- [ ] 启动后的三栏 Shell、会话侧栏、消息流、Composer 和工作面板与用户提供的 PI-Desktop 截图结构一致，且只将产品标识和业务数据替换为 Lion。
- [ ] 新建/恢复会话、Provider/模型/Thinking 设置与 Skills 入口行为不变。
- [ ] 会话可持久化重命名；Composer 输入 `/` 会弹出可筛选、可键盘选择的 Skills 列表。
- [ ] 点击 Composer 不出现 textarea 内层黑色焦点框，仅保留容器级焦点状态。
- [ ] REST history → WS streaming → assistant-ui Thread 的现有端到端路径无需协议修改即可通过。
- [ ] Reasoning、Tool start/update/end、错误、重试/压缩、Permission 与 Plan 审批均有 PI 风格展示并保持原动作语义。
- [ ] Steer、Follow-up、Cancel 和 queue snapshot 契约测试无回归。
- [ ] 深色与浅色主题、空状态、运行态、错误态、审批态均有 Renderer/Electron 截图覆盖。
- [ ] 1280x720 与 2560x1440 下无 document 级横向溢出或 Composer/审批遮挡。
- [ ] `npm test`、`npm run typecheck`、`npm run build` 与相关 Electron Playwright project 通过。
- [ ] 实现 diff 不包含当前工作树中用户未提交的 `styles.css` 修改；除会话重命名的
  `LabelEntry` / REST 窄链路外，不修改 Python，且不修改 Main、Preload 或 shared wire 协议。

## Out of Scope

- PI-Desktop 的 Rust Host、pi Agent Runtime、Zustand store、插件系统、Marketplace、更新器与通知中心。
- 文件树、Diff Review、浏览器、PTY、工作面板真实资源能力、Subagent 拓扑和定时任务；右侧工作面板的 Shell 与空状态属于本次视觉范围。
- 附件、语音、命令面板、会话分支、项目多开和新的后端接口。
- 修改 Lion canonical Session、Provider、Tool Runtime、Capability 或安全边界。
