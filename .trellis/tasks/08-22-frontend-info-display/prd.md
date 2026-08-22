# PR① 信息展示：Skills 浏览与会话信息量

## Goal

纯前端信息展示增强：Skills 浏览、会话列表信息量、permission_mode 徽标、
DocumentTitle。对应设计 PR①（依据 `archive/2026-08/08-22-frontend-task-features-design/design.md`
P0-1 / P0-4 / D4 / D12，证据见其 research/frontend-current-state.md）。

## Requirements

- R1：`api.ts` 新增 `fetchSkills(): Promise<SkillItem[]>`（走 `authorizedFetch`），
  在 `loadData` 的 `Promise.all` 中与 status/sessions/models 一起拉取，
  失败静默降级为空列表。
- R2：Sidebar footer（workspace 目录与 Token 消耗之间）可折叠"可用 Skills"
  区块：默认收起，展开后每条显示 `name` + 截断 `description`。
- R3：点击 skill 条目把 `用 <name> 技能帮我：` 填入聊天输入框并聚焦
  （D4：自然句式；不伪造"用户直接执行 skill"语义）。
- R4：会话列表项第二行显示 `N 条消息` + 相对时间（"今天 14:32" / "3 天前"，
  纯前端格式化不引库）；保留 ID 截断为辅助标识。
- R5：Header 显示 `status.permission_mode` 徽标（纯展示）。
- R6：会话标题写入浏览器标签页（DocumentTitle 模式，跟随当前会话切换）。

## Acceptance Criteria

- [ ] Skills 区块可折叠展开、点击填入引用文案并聚焦输入框。
- [ ] 会话列表显示消息数与相对时间；permission_mode 徽标随 status 更新。
- [ ] 切换/新建会话时浏览器标签页标题联动。
- [ ] `chatProtocol` 等既有测试不回归；`fetchSkills` 有协议契约级单测。
- [ ] `npm run build` 通过，`scripts/build_frontend.py` 产物已更新。

## Out of Scope

- skill 参数表单、执行进度视图、启用/禁用管理；会话标题生成（P2-7 后端）；
  会话重命名/搜索/删除。

## Notes

- 无依赖，可与 PR②③ 并行。触碰面：Sidebar / Header / api.ts / App。
