# 前端任务功能补充实施（父任务）

## Goal

落地 `archive/2026-08/08-22-frontend-task-features-design` 设计终稿的 5 个前端
PR。父任务负责任务地图、跨子任务验收与最终集成审查，不承载直接实现工作。

## 任务地图

| 子任务 | 对应设计 | 交付物 |
| --- | --- | --- |
| 08-22-frontend-info-display | PR①（P0-1 / P0-4 / D12 部分） | Skills 浏览、会话列表信息量、permission_mode 徽标、DocumentTitle |
| 08-22-frontend-run-interaction | PR②（P0-2 / D1 / D7 / D8） | follow_up 排队、steer 显式按钮、队列呈现 |
| 08-22-frontend-run-status | PR③（P0-3 / P1-8） | 重试/压缩状态条、耗时统计行、reasoningDuration |
| 08-22-frontend-toolview-enhance | PR④（P1-5 / P1-6 / D9 / D12 部分） | edit diff 高亮、bash ANSI 卡片、agent 结果卡片 |
| 08-22-frontend-trajectory-lite | PR⑤（P1-7 / D10） | Trajectory 简版轨迹面板 |

## Requirements

- R1：每个子任务独立成 PR、可单独回滚；实现严格遵循设计终稿的方案与
  "不做"边界，越界需回到设计任务修订（已归档，重大变更需重开设计讨论）。
- R2：顺序约束——PR①②③互不触碰同一状态可并行；PR④独立；PR⑤依赖 PR④
  的 ToolView 改动落位（"检查"入口基于新版 ToolView）。依赖关系写入各子
  PRD，不依赖任务树位置表达。
- R3：每个子任务交付时：`npm test`（vitest）通过新增协议层单测、
  `npm run build` 通过、`python scripts/build_frontend.py` 更新随包 dist 产物。
- R4：全程不引入后端改动、不新增协议事件、不加新依赖（ANSI 渲染优先复用
  现有依赖，确需引库先在子任务中说明理由并征得同意）。

## Acceptance Criteria

- [ ] 5 个子任务全部完成、归档，各自 PR 合入 master 且 CI 绿。
- [ ] 集成审查通过：全链路手测清单（见下）逐项过一遍，跨功能交互无回归——
      排队期间显示状态条、轨迹面板正确反映排队/重试事件、ToolView 增强
      不破坏 ①②③ 的展示。
- [ ] 设计终稿中每个 P0/P1 条目都有对应交付物；P2 四项与候选池未被擅自实现。

## 集成审查清单（父任务收口时执行）

1. 新会话 → 发送任务 → 流式期间排队 2 条 + 转向 1 条 → 观察 D7 呈现与消费转换。
2. 断网/错 key 触发重试 → 状态条出现与消失；`/compact` → 压缩提示。
3. 长会话滚动 → Skills 区折叠、列表信息量、标签页标题随会话变化。
4. edit/bash/agent 三类工具调用 → diff 高亮 / ANSI 卡片 / 子任务卡片。
5. 打开轨迹面板 → 历史与实时事件衔接连续；从工具卡片"检查"跳转定位。

## Out of Scope

- P2-7/8/9/10（会话管理、git 面板、subagent 进度接线、Trajectory 完整版）——
  后端配合项，按设计另行立项。
- P2 候选池六项（@ 菜单、TodoPanel、ContextMeter、图片附件、反馈、fork、三栏）。
