# Lion 桌面聊天体验：执行计划

## Checklist

1. 建立 design token、字体、主题和 reduced-motion 基线。
2. 完成 Window shell、title bar、sidebar 与 thread workspace 布局。
3. 实现 workspace chooser、session list、empty state 和 connection/error surfaces。
4. 用 assistant-ui primitives 完成 Thread、Message、Composer 和 ActionBar。
5. 接入 Streamdown、Reasoning、LionToolCard、错误和 stopped run。
6. 实现 Prompt/Steer/Follow-up/Cancel 的 Composer 状态与 QueueIndicator。
7. 实现 Permission/Plan ApprovalSurface。
8. 实现 Provider/Model/Thinking 设置和 first-run 流程。
9. 删除已被新组件替代的桌面临时页面，不改旧 Web 删除范围。
10. 补组件、可访问性、视觉回归和 Electron E2E。

## Validation

```powershell
cd desktop
npm test
npm run typecheck
npm run build
npm run test:a11y
npm run test:visual
npm run test:e2e -- --project=chat-mvp
```

人工检查 Windows 100%/125%/150% 缩放、1280×720 与 2560×1440、深浅主题、reduced-motion、长消息、长工具结果和键盘审批。

## Review Gate

- 逐状态提供截图而不是只展示 happy path。
- 检查不存在第二套 chat store、未批准能力入口和硬编码设计 token。
- 复核 UI 文案准确描述 Recent/当前状态，不把窗口指标写成生命周期总量。
- PR 描述列出依赖/代码行变化、视觉测试矩阵和回滚点。

