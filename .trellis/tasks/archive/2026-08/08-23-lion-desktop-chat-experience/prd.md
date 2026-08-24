# Lion 桌面聊天体验

## Goal

基于稳定的 assistant-ui Runtime，重写 Lion 的桌面聊天界面：参考 Codex 的空间组织、信息密度和交互节奏，同时建立可长期维护的 Lion 自有视觉语言。

## Dependencies

- 依赖 `08-23-electron-host-sidecar` 的窗口、workspace 与连接状态。
- 依赖 `08-23-assistant-ui-protocol-adapter` 的唯一 Runtime、消息 parts 和动作 API。
- 不得绕过 Adapter 直接创建第二套 WebSocket/chat store。
- `08-23-desktop-cutover-web-removal` 必须等待本任务达到桌面主链路验收。

## Requirements

- 使用三段式桌面结构：可折叠左侧工作区/会话导航、中间主线程、按需浮层或窄面板承载设置与审批；MVP 不常驻右侧轨迹面板。
- 新建 Lion design tokens，覆盖颜色、字体、间距、圆角、阴影、动效和状态语义；深浅主题同等支持。
- 会话列表支持当前态、新建、恢复、相对时间、消息数量和当前 workspace 信息。
- 空状态强调工作区与任务意图，不使用通用聊天机器人营销卡片。
- Thread 支持稳定流式滚动、用户/助手消息、Streamdown、Reasoning、Tool、错误和停止状态。
- Composer 支持普通提交、运行中 Steer/Follow-up、停止、队列计数、模型/Thinking 快捷入口和 Skill 提示。
- Permission 与 Plan 审批必须明确操作影响、默认安全选择和键盘焦点，不用 toast 代替阻塞决策。
- 设置覆盖 Provider、模型、API 地址/凭证与 Thinking；敏感值不得回显完整内容。
- 界面在 sidecar starting/failed/exited、WS reconnecting 和 API 未配置时提供明确恢复路径。
- 组件优先使用 assistant-ui/Radix primitives；只复制实际使用的 shadcn 源码，不导入完整组件仓库。

## Acceptance Criteria

- [ ] 1280×720 到 2560×1440 桌面窗口内无关键控件遮挡或横向溢出。
- [ ] 左侧栏可折叠，主线程保持可读宽度，长会话滚动和流式锚定稳定。
- [ ] 空状态、会话态、流式态、工具态、审批态、错误态和断连态均有完整视觉验收截图。
- [ ] Tool running/completed/error、Reasoning streaming/completed 和 stopped run 容易区分且不过度抢占正文。
- [ ] Composer 的 Prompt、Steer、Follow-up、Cancel 与队列反馈可通过键盘和鼠标完成。
- [ ] Permission/Plan 审批具备焦点圈、Esc/默认行为和屏幕阅读器标签。
- [ ] Provider/API 未配置可以在桌面内完成首次配置并回到聊天。
- [ ] 深浅色主题通过对比度和高频状态视觉检查。
- [ ] UI 不包含终端、Diff、文件树、附件、轨迹瀑布或多工作区并行入口。
- [ ] 组件测试、可访问性检查、视觉回归和 Electron 聊天主链路 E2E 通过。

## Out of Scope

- Codex 像素复刻或 OpenAI 品牌元素。
- PTY、Diff、文件浏览器、附件、语音、消息分支和编辑历史消息。
- 全量响应式移动端或浏览器适配。

