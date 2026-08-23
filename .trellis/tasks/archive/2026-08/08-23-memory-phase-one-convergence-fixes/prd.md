# 收敛一期记忆系统实现

## Goal

让当前 Memory 实现重新符合用户最终确认的 `6c9fddd` 一期契约，并关闭验收报告中的 2 个 P1 与 6 个 P2 finding。

## Source of Truth

1. 用户最终确认的 `6c9fddd` 一期边界，已收敛进三个 child PRD 与
   `.trellis/spec/backend/memory-capability.md`；
2. `.trellis/tasks/08-23-memory-system-acceptance-review/research/acceptance-report.md`；
3. 当前源码与架构规范。

发生冲突时，以第一项的产品边界为准；验收报告只描述实现偏差。旧归档任务描述的是
被否决的 handoff/query-aware 方案，不再作为本任务输入。

## Delivery Boundary

- `08-23-memory-store-task-ledger-fix`：canonical schema、Task Ledger、显式工具、MemoryPolicy 与治理契约。
- `08-23-memory-context-boundary-fix`：普通 pinned ContextLayer，并删除通用 QueryContext SPI 与 handoff；Memory 专属 auto-recall 和 eager composition 已在前一 child 收敛。
- `08-23-memory-lexical-recall-prototype`：独立离线实验，不接生产数据库。

三个 child 独立验收和提交，按上述顺序交付；父任务只做最终集成验收。

## Acceptance Criteria

- [x] 验收报告的 2 个 P1 与 6 个 P2 finding 均有对应 child 和回归测试。
- [x] 产品只有 Task Ledger 与四象限 Semantic Memory 两种记录模型。
- [x] 一期没有 Session handoff、query-aware SPI、生产 FTS、revision/stale 状态或后台提炼。
- [x] FullProfile 保持 Memory 能力，但构造阶段不创建数据库。
- [x] 三个 child 分别通过定向验证，最终通过完整 Trellis check 与 CI 门禁。

## Out of Scope

- AGENTS/CLAUDE loader 重构；它不被 Memory 自动采集即可。
- 二期自动 relevant recall、embedding、跨 clone identity 或旧 schema migration。
- 打开、修改或清理用户真实 `~/.lion-code/memory.sqlite3`。
