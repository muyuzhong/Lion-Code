# 修正 Memory Store、Task Ledger 与治理工具

## Goal

用最小 canonical store 替换旧的 FTS/revision/stale 模型，补齐任务续接、类型化 evidence、治理工具和静态 MemoryPolicy。

## Requirements

- SQLite 只保留 `semantic_entries`、`tasks` 和必要索引；不实现旧 schema migration、兼容层、FTS、revision 或 persisted stale。
- 构造 `MemoryStore` 不访问文件系统；首次实际 read/write 原子初始化或验证 schema，未知版本/损坏 fail closed。
- `tasks` 支持当前 project 内 create/update、0/1/N open recall、complete/reopen、archive/restore/purge；不保存 transcript 或逐轮日志。
- Semantic Memory 支持四象限、规范化 stable key、原位更新、typed evidence、exact/literal recall、动态 review 和 archived view。
- `needs_review` 由 90 天验证期或任一记录 path 缺失动态计算，不能写入数据库状态；普通 recall 必须排除。
- 普通 remember/manage 无确认；pin/unpin 与 purge 使用独立确认工具。remember 不得覆盖 pinned，archive 清 pin，restore 保持非 pinned。
- `validate` 必须携带新的 `user_request|source|test|command` evidence。
- Capability 提供简短静态 MemoryPolicy PromptLayer；所有模型可见操作仍走 ToolRuntime。

## Acceptance Criteria

- [ ] 干净 Session 可通过 `recall_tasks` 得到当前 project 的 0/1/N open tasks，其他 project 不泄漏。
- [ ] task 可创建、整体更新、完成、重开、归档、枚举归档、恢复和 purge。
- [ ] 四象限约束、typed evidence、path/ref、stable key 唯一性和 restore 冲突均由测试覆盖。
- [ ] remember 默认非 pinned 且无需确认；pin/unpin/purge 需要确认；其他可逆动作不需要确认。
- [ ] pinned 内容不能由 remember 或 restore 绕过确认重新注入。
- [ ] age/path review 会同时排除 explicit semantic recall，validate 新证据后恢复可用。
- [ ] archived view 返回可 restore 的 semantic/task id，不要求调用者记住旧 id。
- [ ] 仅构造 store 不创建数据库；fresh DB 并发首开不失败；未知 schema 不被覆盖。
- [ ] MemoryPolicy 只描述按需 recall、显著里程碑更新、写入资格和权威优先级。

## Out of Scope

- 普通 Pinned ContextLayer、通用 QueryContext SPI 和 Session handoff 删除，由下一 child 负责；本 child 已移除 Memory 专属 auto-recall layer 以保持独立可验证。
- 离线 tokenizer 实验和任何生产自动 relevant recall。
