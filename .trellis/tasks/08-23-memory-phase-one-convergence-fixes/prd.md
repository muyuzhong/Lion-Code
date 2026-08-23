# 收敛一期记忆系统实现

## Goal

让当前 Memory 实现重新符合用户最终确认的 `6c9fddd` 一期契约，并关闭验收报告中的 2 个 P1 与 6 个 P2 finding。

## Source of Truth

1. `.trellis/tasks/archive/2026-08/08-22-memory-system-design-convergence/`；
2. `.trellis/tasks/08-23-memory-system-acceptance-review/research/acceptance-report.md`；
3. 当前源码与架构规范。

发生冲突时，以第一项的产品边界为准；验收报告只描述当前偏差。

## Delivery Boundary

- `08-23-memory-store-task-ledger-fix`：canonical schema、Task Ledger、显式工具、MemoryPolicy 与治理契约。
- `08-23-memory-context-boundary-fix`：普通 pinned ContextLayer、lazy composition，并删除 handoff/query-aware 自动召回。
- `08-23-memory-lexical-recall-prototype`：独立离线实验，不接生产数据库。

三个 child 独立验收和提交，按上述顺序交付；父任务只做最终集成验收。

## Acceptance Criteria

- [ ] 验收报告的 2 个 P1 与 6 个 P2 finding 均有对应 child 和回归测试。
- [ ] 产品只有 Task Ledger 与四象限 Semantic Memory 两种记录模型。
- [ ] 一期没有 Session handoff、query-aware SPI、生产 FTS、revision/stale 状态或后台提炼。
- [ ] FullProfile 保持 Memory 能力，但构造阶段不创建数据库。
- [ ] 三个 child 分别通过定向验证，最终通过完整 Trellis check 与 CI 门禁。

## Out of Scope

- AGENTS/CLAUDE loader 重构；它不被 Memory 自动采集即可。
- 二期自动 relevant recall、embedding、跨 clone identity 或旧 schema migration。
- 打开、修改或清理用户真实 `~/.lion-code/memory.sqlite3`。
