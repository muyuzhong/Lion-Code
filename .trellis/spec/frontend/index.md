# Frontend Spec Index

前端（`frontend/`，React + TypeScript + vite + vitest）编码规范入口。

## 文件清单

- [chat-queue-contract.md](chat-queue-contract.md) — 聊天队列事件契约：queue_update 快照语义与消费出队规则（跨层契约，改队列相关代码必读）
- [runtime-events-contract.md](runtime-events-contract.md) — 运行时事件契约：重试/压缩两层事件架构、状态条生命周期、耗时统计边界（改 runtimeNotice/metrics/轨迹面板必读）

## Pre-Development Checklist

- [ ] 读任务 PRD 引用的归档设计终稿（`.trellis/tasks/archive/2026-08/08-22-frontend-task-features-design/design.md`）的对应 PR 段落与"不做"边界
- [ ] 改队列相关代码前读 [chat-queue-contract.md](chat-queue-contract.md)；改状态条/统计/思考耗时前读 [runtime-events-contract.md](runtime-events-contract.md)
- [ ] 协议层（chatProtocol.ts）改动必须配套 chatProtocol.test.ts 契约级单测
- [ ] 不新增依赖前先确认现有依赖（lucide-react 图标、既有工具函数）无法满足

## Quality Check

- [ ] `cd frontend && npm test` 全过（含新增契约单测）
- [ ] `npm run build`（含 tsc -b 类型检查）通过
- [ ] 仓库根目录 `python scripts/build_frontend.py` 已同步随包 dist 产物，index.html 引用与 assets 一致、无孤儿文件
- [ ] 源码注释只写设计原因/边界约束（中文），无逐行翻译
