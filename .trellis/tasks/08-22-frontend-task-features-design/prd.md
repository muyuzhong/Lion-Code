# 前端任务展示功能设计与补充规划

## Goal

系统化记录 Lion Web 前端"任务功能"的现状基线与 8 项补充设计，形成可直接拆分为
独立 PR 的设计文档。本任务只做设计，不改产品代码。

## Background

- "任务"在 Lion Web 前端没有独立实体：一次任务 = 会话内一次 Agent 执行，UI 围绕
  "会话 → 消息流 → 执行过程"组织。现状清单见
  `research/frontend-current-state.md`。
- 调研发现一批功能**后端与协议层已就绪、只差前端展示**（Skills 列表、steer 排队、
  重试/压缩状态、permission_mode、messageCount），以及若干需要少量新代码
  （diff 渲染、子任务进度）或后端配合（会话管理、git 状态）的缺口。
- 项目原则：选最简单实现、不预防性抽象；一个 PR 只承载一个职责、可独立回滚。
  设计按此原则排序与拆分。

## Requirements

- R1：以 `research/frontend-current-state.md` 为唯一证据基线，每项设计标注现状
  证据（文件:行号）、问题、设计方案、明确不做的事。
- R2：设计按实施优先级分层——P0（后端/协议已就绪，仅前端接线）、P1（前端少量
  新代码）、P2（需后端配合）——且每项可独立验收、独立成 PR。
- R3：P0 各项不得引入后端改动、新依赖或新协议事件；只消费既有 API 与既有
  ServerEvent。
- R4：steer/follow_up 设计必须与 bridge 现有语义一致：运行中 `prompt` 被拒，
  补充指令走 `steer` / `follow_up`；排队状态只展示（撤销排队需要新协议 action，
  记为后续扩展，不在本轮设计内实现）。
- R5：skill 是 agent 侧工具（`skill` tool），前端只做浏览与引用辅助，不伪造
  "用户直接执行 skill"的语义。
- R6：子任务（subagent）设计不新增后端事件时，必须基于 `tool_execution_update`
  的 `partialResult` 呈现进度；结构化子代理事件流列为可选扩展，另行设计。
- R7：需要后端配合的项（会话标题/删除/搜索、git 状态面板）只记录接口形态与
  边界问题，接口契约在各自实现任务中细化。
- R8：设计文档给出 PR 拆分计划，每个 PR 一个职责，标注依赖关系与回滚点。

## Acceptance Criteria

- [ ] `research/frontend-current-state.md` 完整记录前端组件、API 面、协议事件
      （含被 reducer 忽略的事件）与后端能力缺口的对照。
- [ ] `design.md` 覆盖 8 项补充设计（P0×4、P1×2、P2×2），每项含现状证据、
      设计方案、UI 形态、数据流与"不做"边界。
- [ ] P0 各项设计均不要求后端改动或新依赖。
- [ ] `design.md` 给出 PR 拆分计划（每项一个独立 PR，P2 项标注需后端配合）。
- [ ] 设计评审通过后，后续实现按 PR 计划另建实现任务（或本任务转实施），
      本轮不执行 `task.py start`。

## Out of Scope

- 产品代码修改、前端构建、`task.py start`、PR 创建。
- 排队指令撤销、结构化 subagent 事件、会话分支/消息编辑重发等新协议能力设计。
- 后端接口实现与契约测试设计（P2 项仅记录接口形态）。
