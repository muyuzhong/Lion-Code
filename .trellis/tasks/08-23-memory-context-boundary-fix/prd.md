# 收敛 Memory 上下文与会话边界

## Goal

在 canonical store 修正后，只保留一期需要的普通 pinned ContextLayer，并删除 rejected Session handoff 与 query-aware 自动召回复杂度。

## Requirements

- 删除 Session handoff API、application facade 和专属测试；不改 Compaction 本身。
- 删除只为自动 relevant recall 增加的 QueryContextLayer SPI、FTS query 路径和对应架构契约。
- Memory 使用现有普通 ContextLayer 注入 active、pinned、非 needs-review 的 long-term + current-project 条目。
- 固定 512-token/8-entry 预算；单条超限使用 `continue`，后续可容纳条目仍参与选择，overflow 可由 review 枚举。
- FullProfile 默认注册 Memory，但构造阶段不得创建数据库；Coding/Minimal 和 extension override 保持。
- prepared projection 不写 Session/JSONL/Memory，不调用 Provider。

## Acceptance Criteria

- [ ] 过期或任一路径失效的 pinned 条目不注入。
- [ ] 大条目排第一时，后续可容纳小条目仍会注入。
- [ ] 无条目时不渲染空块，输出保持稳定排序和固定预算。
- [ ] 构造 FullProfile 不创建数据库；首次 prepare 才显式访问。
- [ ] Session/Runtime/Application 不再暴露 handoff，Compaction 九段协议保持。
- [ ] 产品没有 query-aware Memory layer、FTS/relevant 自动召回或 recall 写回。

## Dependency

必须在 `08-23-memory-store-task-ledger-fix` 完成后实施。
