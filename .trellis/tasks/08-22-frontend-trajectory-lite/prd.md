# PR⑤ Trajectory 简版轨迹面板

## Goal

零后端的执行轨迹视图：右侧滑出面板，纵向时间线呈现历史与实时事件，
工具卡片"检查"联动定位。对应设计 PR⑤（依据归档设计 P1-7 / D10；对照项目
形态见归档 research/deepseek-harness-frontend-inventory.md，数据面差异表
决定简版边界）。

## Requirements

- R1：Header 增加"轨迹"按钮，打开右侧滑出面板（Sheet），不做三栏布局重构。
- R2：数据两段拼合——历史：`/api/messages` + 会话 entry 时间戳
  （消息级：用户/助手/工具结果，状态与耗时推导）；实时：WS 事件本地打点
  （`performance.now()`）。拼合逻辑为独立纯函数（折叠器）便于单测。
- R3：纵向时间线——每行 = 事件类型图标 + 摘要 + 耗时条（相对行宽比例）；
  行类型：用户消息 / 助手消息 / 工具调用（状态色）/ 压缩 / 自动重试；
  点行展开详情（入参出参复用现有折叠渲染）。
- R4：ToolView 卡片增加"检查"入口，打开轨迹面板并滚动定位到该调用。
- R5：流式更新停在尾部；面板关闭不中断事件采集（数据层常驻）。

## Acceptance Criteria

- [ ] 打开面板能看到当前会话完整消息级时间线，历史与实时衔接无重复/断档。
- [ ] 工具行显示状态色与耗时条；点行展开入参出参。
- [ ] 从任意工具卡片"检查"可跳转定位。
- [ ] 轨迹折叠器（历史 + 实时合并、去重）有纯函数单测。
- [ ] `npm run build` 通过，dist 产物已更新。

## Out of Scope

- 后端事件持久化 / 分页 / request inspection（system prompt、usage、retry、
  prompt diff）——P2-10；Network 式横向时间线交互（拖选/缩放）；TTFT 与
  解码速率。

## Notes

- **依赖 PR④**：ToolView"检查"入口基于 PR④ 落位后的组件。触碰面：
  新组件（面板/折叠器）/ Header / ToolView / useLionChat（事件采集）。
