# Lion 桌面聊天体验：设计

## Information Architecture

```text
Title bar / workspace identity / connection status
├─ Sidebar
│  ├─ New task
│  ├─ Sessions
│  └─ Skills + usage summary
└─ Thread workspace
   ├─ Compact task header
   ├─ Assistant Thread viewport
   ├─ blocking approval surface
   └─ Composer rail
```

设置使用 modal/sheet；审批属于主任务流，显示在 Thread/Composer 邻近位置并保持焦点，不放入通用设置面板。

## Design Language

- Lion 品牌以暖金/琥珀作为低面积强调色，主体使用中性灰阶；危险、成功、等待使用语义色而非品牌色。
- UI 字体与代码字体分离，正文宽度和行高优先可读性；工具输出密度高于自然语言正文。
- 边框和层级靠细微明度/阴影变化，不大量使用圆角气泡与彩色渐变。
- 动效只解释状态变化：侧栏、审批出现、tool 展开、stream settle；遵守 reduced-motion。

具体 token 在实现前以 CSS variables 固化，不允许组件内散落颜色和 spacing magic numbers。

## Component Map

- assistant-ui：Thread、Message、Composer、ThreadList、ActionBar 等交互 primitives。
- Streamdown：assistant text part。
- Radix：Dialog、Popover、Tooltip、Select、Collapsible、ScrollArea 等基础行为。
- 自有组件：WorkspaceSwitcher、ConnectionState、LionToolCard、ReasoningTimeline、ApprovalSurface、QueueIndicator、ProviderSettings。
- Sonner 只承载非阻塞通知；错误恢复和审批不用 toast 作为唯一界面。

## State Surfaces

| State | Surface |
| --- | --- |
| no workspace | dedicated workspace chooser |
| sidecar starting | boot screen with bounded progress text |
| sidecar failed/exited | diagnostic page with safe retry/reselect actions |
| API unconfigured | first-run provider setup |
| WS reconnecting | inline connection status, composer disabled |
| blocking approval | focused approval surface near current run |
| run streaming | stop action + steer/follow-up affordance |
| settled | normal composer + message actions |

## Accessibility and Keyboard

- 所有 icon-only control 有 accessible name 和 tooltip。
- 主要区域、Thread、Composer、审批和设置形成可预测 tab 顺序。
- 焦点不因流式 delta 重置；弹窗关闭后回到触发器。
- 颜色不是状态的唯一编码；错误、进行中和完成同时使用图标/文本。

## Rollback

回滚本 PR 恢复 Child 2 的基础 assistant-ui Thread 外观；宿主、协议、Python API 和 Session 数据不受影响。

