# Implementation Plan

- [ ] 读取 canonical store 的 pinned/review API，替换 MemoryQueryContextLayer 为普通 ContextLayer。
- [ ] 删除 QueryContextLayer SPI、query 提取和自动 relevant recall。
- [ ] 删除 Session handoff 生产路径与测试，保持 Compaction 契约不变。
- [ ] 修正预算 head-of-line、age/path 过滤和 overflow reporting。
- [ ] 调整 composition 与架构测试，证明 lazy FullProfile、profile 隔离和 prepared-only。
- [ ] 运行 context/session/composition/architecture 定向测试与质量门禁。
