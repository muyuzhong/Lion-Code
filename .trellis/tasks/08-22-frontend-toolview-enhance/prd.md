# PR④ ToolView 增强：diff / ANSI / 子任务卡片

## Goal

按工具类型升级 ToolView 展示：edit 的 diff 高亮、bash 的 ANSI 终端卡片、
`agent` 的子任务结果卡片。对应设计 PR④（依据归档设计 P1-5 / P1-6 与
D9 / D12；工具输出格式证据见归档 research/frontend-current-state.md §5.2、§5.3）。

## Requirements

- R1（diff）：判定为"修改代码"（edit/replace 类）的工具，检测 `result` 含
  `@@ ... @@` hunk → `<SyntaxHighlighter language="diff">` 渲染（增绿删红），
  否则回退纯文本；创建/写入类保持纯文本预览。
- R2（ANSI）：bash / 命令类工具结果含 ANSI 转义序列时渲染终端风格卡片
  （黑底等宽 + 颜色）；优先复用现有依赖，确需新库须先说明理由征得同意。
- R3（agent 卡片）：`toolName === "agent"` 的调用渲染为子任务卡片——
  头部 `agent · <type> · <description>` + 状态徽标，正文 result 按 Markdown
  渲染；`prompt` 沿用现有入参折叠区，不加专属折叠区（D9）。
- R4：实现顺序 diff → ANSI → agent 卡片；非 edit/bash/agent 工具的展示
  完全不受影响（回归零容忍）。

## Acceptance Criteria

- [ ] edit 工具结果出现红绿 diff 高亮；write 工具仍是行号预览。
- [ ] bash 结果含 ANSI 色彩时正确渲染，无转义序列时不破坏纯文本。
- [ ] agent 调用显示子任务卡片头部与 Markdown 正文。
- [ ] diff / ANSI 检测为纯函数并有单测；既有测试不回归。
- [ ] `npm run build` 通过，dist 产物已更新。

## Out of Scope

- 多 hunk 合并视图、行内语法叠加、跳转编辑器；子任务实时进度（P2-9）；
  递归工具树（子代理嵌套场景）。

## Notes

- 无前置依赖，建议在 PR①②③ 之后开工（同改前端避免冲突）。触碰面：
  ToolView（及其新增子组件）。
