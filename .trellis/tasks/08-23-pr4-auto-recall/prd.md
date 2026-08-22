# PR4 Query-aware 自动召回与 FullProfile 集成

Parent：`08-22-memory-system-design-convergence`（对应其 implement.md 的 PR4 段）

依赖：**PR3（memory store）已合并**；PR1 建议先合并以建立清晰权威优先级，但不是代码依赖。

## Goal

让 pinned 和 relevant memory 在 prepared context 中可靠、低噪声地出现，而不依赖模型主动调用工具。

## Requirements

- R1：增加窄 `QueryContextLayer` SPI：`render(query: str, view: ContextView) -> str`，输入最新 user query + immutable ContextView，输出 prepared-only text。
- R2：ContextManager 从当前 prepared messages 取最新 user query；输出只进入本次 prepared provider context，不写 canonical Session；本地同步 SQLite 查询，不调用 Provider；同一 provider tool loop 使用同一 latest user query；不引入缓存失效协议。
- R3：不恢复旧 TurnParticipant/ProjectionLayer/provider-side query service；CapabilityRegistry 只聚合该纯投影；Runtime 不持有 MemoryStore。
- R4：Memory layer 渲染 long-term + current-project active pinned（固定 400-token 预算，超限按 project 优先、kind、stable_key 稳定截断），并按 latest user query 召回 relevant（top 6、800-token 预算、总注入 ≤1200 tokens）；空结果不注入噪声块。
- R5：召回只允许 long-term + 当前 project 的 active 条目；scope/status 硬过滤、FTS5 BM25、exact key/path boost、最低命中门槛。
- R6：分区展示（pinned/relevant），附 memory id、scope、kind、evidence；末尾权威性说明。
- R7：FullProfile 默认选择新 Memory Capability；Coding/Minimal 不变，caller `extension_specs` 契约保持。
- R8：扩展 legacy-removal gate：允许新 capability-owned store/query layer，继续禁止旧模块与符号。

## Acceptance Criteria

- [ ] prompt ordering、权威性说明测试通过。
- [ ] 每 user turn 刷新、tool-loop 内稳定测试通过。
- [ ] restore/new/handoff 交互不破坏召回语义。
- [ ] 空结果不注入；不相关 query 不召回（防串扰）测试通过。
- [ ] 架构不可达测试（Runtime 不持 Store、不写 Session、不二次调用 LLM）通过。
- [ ] CI 基线全绿。

## Out of Scope

- 硬行为门控（Hook/Permission/workflow gate，另行任务）。
- embedding/向量检索、缓存协议。

## 回滚点

取消 QueryContextLayer 注册与 FullProfile 选择；手动 Memory tools 与数据库仍可用（PR3 能力不受影响）。
