# Memory 上下文边界修正设计

Memory Capability 注册一个普通 `ContextLayer`，从同一 lazy store 读取可注入 pinned 条目。选择与 review 复用同一纯函数/查询，不建立 query-aware SPI。

删除 handoff 和 QueryContextLayer 时同步删除真实调用者、公开 facade、架构门禁和只验证旧功能的测试；不保留 alias 或 deprecation wrapper。

FullProfile 仍构造一个 store 供 tools/layer 共享，但构造对象不触发数据库 open。取消 Capability 注册即可停用，数据库保留。
