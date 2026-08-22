# Lion 内建 Memory — 平衡型技术设计（handoff UX 已确认：显式操作）

## 1. 修订结论

上一版的四象限语义是对的，但实现过轻，漏掉了三个真实要求：

1. **任务连续性**：未完成任务需要跨 Session handoff，而不是被排除为“一次性进度”；
2. **召回可靠性**：依赖模型主动调用 `recall_memory`，会重复 AGENTS “看得到但不执行”的问题；
3. **治理能力**：纯 JSON + exact-key scan 无法很好处理相关性、过期、归档和修订链。

新的取舍是：Memory 直接内建 Lion，采用 SQLite/FTS5 和自动 prepared-context 召回，但不引入 embedding、后台 LLM、cron 或独立服务。

## 2. 三条边界，而不是一个万能 Memory

```text
Lion Product
├─ Project Instructions                 权威规则，不是 Memory
│    └─ AGENTS / CLAUDE loader -> system prompt
├─ Task Handoff                         临时工作连续性
│    └─ canonical Session + Compaction + BranchSummaryEntry
└─ Semantic Memory Capability           跨会话稳定知识/行为
     ├─ long_term/project × definition/behavior
     ├─ SQLite + FTS5
     ├─ pinned + query-relevant prepared context
     └─ remember / recall / review / manage tools
```

这是一个产品级“记忆体验”，但保持两个状态 owner：Session 拥有任务历史和 handoff；MemoryStore 只拥有稳定语义条目。这样既解决用户的连续性问题，又不复制 transcript。

## 3. 场景推导

### 3.1 上下文不足后开新会话

当前 Compaction 已强制输出九个章节：Objective、Constraints、Decisions、Repository State、Findings、Failed Attempts、Completed Work、Remaining Work、Verification。它已经是合格的 handoff 载荷。

缺口不是“再建一个 working-memory 数据库”，而是缺少产品动作：

```text
current canonical Session
  -> 复用 ContextCompactor 生成九段有界摘要
  -> 保留旧 Session
  -> 创建新 Session
  -> 追加 BranchSummaryEntry(summary, branch_root_id)
  -> 新 Session 从摘要继续
```

不复制旧 raw messages，不把任务进度写入 semantic-memory SQLite。用户仍可 restore 旧 Session 查看完整历史。

待用户确认的 UX：推荐新增显式 `handoff_session` / “Continue in new session”，普通 `new_session` / clear 继续表示干净会话。自动对所有 new session 携带任务会让“彻底清空”变得含糊。

**已确认（2026-08-23）**：采用显式 `handoff_session` 操作；普通 `new_session` / clear 保持干净会话语义。

### 3.2 AGENTS 中的 CI 规则经常不执行

源码显示 loader 存在，但生产没有调用 `load_claude_md()`。因此第一根因是项目指令根本可能未进入 Full product prompt；这必须独立修复，不能用 Memory 掩盖。

修复后有两种合理承载方式：

- 项目专属、权威规则继续只放 AGENTS；
- 跨项目都适用的 PR 流程可记为 `long_term + behavior + pinned`，在每个 Provider 请求靠近当前上下文重复出现。

Memory 能显著提高行为显著性，但不能保证模型绝不违背自然语言。需要硬保证时，应把 “CI 未绿禁止 merge” 写成现有 pre-tool Hook/Permission 或专用 workflow gate；Memory 不做命令解释器。

## 4. Semantic Memory 模型

### 4.1 四象限保持不变

| scope | definition | behavior |
| --- | --- | --- |
| long_term | 用户环境、稳定偏好、跨项目事实 | 跨项目协作和工程流程 |
| project | 架构、所有权、决策、项目事实 | 项目特定规则、失败模式、验证关卡 |

### 4.2 统一条目

数据库使用一张 current/revision table，通过 CHECK 约束保证 definition 与 behavior 契约：

```text
MemoryEntry
- id: integer primary key
- scope: long_term | project
- project_key: nullable; project 必填，long_term 必须为空
- kind: definition | behavior
- stable_key: scope + project_key + kind 内可读键
- content: definition statement 或 behavior instruction
- trigger: behavior 必填；definition 必须为空
- recall_mode: pinned | relevant
- status: active | stale | archived
- evidence_json: 非空字符串列表
- paths_json: project 可选；long_term 必须为空
- source_session_id: 可选
- created_at / updated_at / validated_at
- supersedes_id: 可选，指向被本 revision 替代的旧 revision
- archived_reason: stale/archive 时记录原因
```

修正同一 stable key 时创建新 active revision，并把旧 revision 置为 archived；不按时间戳自动选择事实。FTS 只索引 active/stale 可管理内容，自动召回只选 active。

不保存置信度、embedding、任意 metadata blob、use-count 排序权重或模型生成的语义分数。

## 5. 存储

```text
~/.lion-code/memory.sqlite3
```

一个数据库容纳 long-term 和所有 project，通过 `project_key` 硬隔离，不为每个 scope 建一套 repository。

建议表：

- `memory_entries`：条目 revision 与生命周期；
- `memory_fts`：FTS5 虚拟表，索引 stable_key、content、trigger、paths；
- `memory_meta`：唯一 schema version 和 maintenance metadata。

SQLite 使用事务、foreign key、busy timeout 和 WAL；schema 不匹配或 integrity check 失败时 fail closed。当前实现只接受准确的 v1 schema，不提供旧 Memory migration、兼容读取、fallback 或静默重建。

选择 SQLite 的理由不是条目数量，而是当前需求已经要求：FTS 相关性、事务修订、状态过滤、归档恢复和 review 查询。继续使用 JSON 会在应用层重写一个更差的数据库。

## 6. 自动召回

### 6.1 新的窄投影 seam

现有 ContextLayer 看不到 user query，普通 PromptLayer 又无法做相关召回。增加一个新的 `QueryContextLayer`：

```text
render(query: str, view: ContextView) -> str
```

- ContextManager 从当前 prepared messages 取最新 user query；
- 输出只进入本次 prepared provider context，不写 canonical Session；
- 本地同步 SQLite 查询，不调用 Provider；
- 同一 provider tool loop 使用同一个 latest user query，FTS 查询保持确定性；个人规模下不为此增加缓存失效协议；
- 不恢复旧 `TurnParticipant.before_turn`、ProjectionLayer 或 provider-side query service。

CapabilityRegistry 只聚合该纯投影。Memory Capability 是首个消费者；Runtime 不持有 MemoryStore。

### 6.2 两阶段选择

**Pinned 集合**

- active + recall_mode=pinned；
- long-term 与当前 project；
- 每次 Provider request 都渲染；
- 固定预算建议 400 tokens，超限按 project 优先、kind、stable_key 稳定截断并在 review 报警。

**Relevant 集合**

1. scope/status 硬过滤：long-term + 当前 project + active；
2. FTS5 BM25 搜索 stable_key/content/trigger/paths；
3. exact stable_key/path 命中加固定 boost；
4. 达不到最低 lexical hit 的条目不返回；
5. 最多 6 条、建议 800 tokens；
6. 每次 prepared request 用 latest user query 重新执行本地查询；结果由稳定排序保证一致，不引入缓存状态。

总 Memory 注入建议不超过 1,200 tokens。无 pinned 且无 relevant 时返回空字符串，不制造空 `<memory>` 噪声。

不使用 recency/recall-count 参与排序，避免“被召回所以更常被召回”的反馈回路；时间只用于 health review。

### 6.3 输出形状

```text
# Active Memory
## Pinned Behaviors
- [m:42 long_term/behavior] When: ... Do: ... Evidence: ...

## Relevant Definitions
- [m:87 project/definition] ... Evidence: ...

## Relevant Behaviors
- [m:91 project/behavior] When: ... Do: ... Evidence: ...

Memory is historical context. Current user instructions, AGENTS, source and tests win.
```

ID 和 evidence 让模型能显式验证、更新或报告噪声。

## 7. 写入、验证与治理

### 7.1 工具面

- `recall_memory(query, paths=(), include_inactive=false)`：诊断或中途刷新；默认只读 active。
- `remember_definition(scope, stable_key, content, evidence, paths=(), recall_mode="relevant")`。
- `remember_behavior(scope, stable_key, trigger, instruction, evidence, paths=(), recall_mode="relevant")`。
- `review_memory(scope="all", older_than_days=90)`：列 stale、长期未验证、pinned overflow、revision 链和 archive 数量。
- `manage_memory(id, action, reason)`：`mark_stale | archive | restore | validate | purge`。

remember/manage mutation 需确认；recall/review 只读。`purge` 物理删除指定 revision，archive 可恢复。

### 7.2 命中时验证

- project 条目有 paths 时，召回前只检查规范化项目相对 path 是否仍存在；
- paths 全部不存在时，从本次自动结果剔除，并把 id/reason 作为 stale candidate 提供给 `review_memory`；
- 不自动执行 command evidence，不让 Memory 在召回路径运行代码；
- 当前源码/AGENTS 与条目冲突时，由活跃模型报告并用 manage/remember 显式处理。

QueryContextLayer 保持纯读取：自动召回不修改数据库。用户确认 `mark_stale` 后才持久化状态；没有自动 archive、purge、语义合并或 newer-wins。

### 7.3 写入闸门

只有以下内容适合 active Memory：

- 用户明确要求长期记住；
- 已由当前源码/测试/命令验证并会跨会话复用；
- 行为 trigger 可以明确判断；
- evidence 足以让未来 Agent 重新核对。

任务进度走 handoff；原始会话摘要、瞬时错误、秘密、猜测和一次性 TODO 不进入 Semantic Memory。

MVP 不做 task-end LLM extractor。Lion 目前没有可靠的“任务完成”终态，普通 assistant stop 只代表一轮结束；自动提炼会产生错误时机和第二写者。未来若需要，只能先生成非 active candidate，再经确认激活。

## 8. AGENTS、Memory 与强制策略

| 内容 | 正确 owner | 可靠性机制 |
| --- | --- | --- |
| 当前项目必须遵守的规则 | AGENTS | 默认 Full system prompt 实际加载 |
| 跨项目、需高显著性的个人行为 | long-term pinned behavior | 每个 Provider request prepared injection |
| 与当前问题相关的历史经验 | relevant semantic memory | 每个 user turn FTS5 选择性召回 |
| 必须绝对禁止/保证的动作 | Hook / Permission / workflow gate | ToolRuntime 执行前硬判定 |

这四者可以协作，但不能互相冒充。

## 9. 组合与所有权

- FullProfile 默认启用 Semantic Memory；Coding/Minimal 保持不变，仍可通过 `extension_specs` 显式添加。
- Memory Capability 贡献 tools、普通 PromptLayer（可信度说明）、QueryContextLayer 和必要资源关闭，不贡献 Runtime owner。
- MemoryStore 只由 Capability 内部 tool/query adapters 持有；AgentComposition 不公开 repository。
- TaskHandoff 是 application/facade 对 SessionRuntime + ContextRuntime 的显式协调，不由 MemoryStore 写 Session。
- Supervisor Checkpoint 继续只保存执行控制字段，不保存 handoff 或 semantic memory。

## 10. 风险与取舍

| 选择 | 得到 | 代价/控制 |
| --- | --- | --- |
| SQLite + FTS5 | 相关检索、事务、生命周期治理 | 比 JSON 多 schema/索引代码；标准库内置且有针对性测试。 |
| 每 user turn 自动 recall | 不依赖模型主动调用 | 可能增加少量噪声；用硬过滤、阈值、top-k、预算和空结果抑制。 |
| pinned 每次注入 | 关键行为更显著 | pinned 过多会稀释注意力；设 400-token 上限并在 review 报警。 |
| handoff 新 Session | 用户无需重写任务提示 | 摘要仍可能遗漏；保留旧 Session，可恢复核对。 |
| stale/archived/revision | 可治理、可恢复、可追溯 | 状态模型更重；每个状态对应真实清理需求。 |
| 不做 embeddings/后台 LLM | 本地、低运维、污染面小 | 语义改写召回较弱；先用 coding 领域更适合的 FTS/path 证据验证。 |

## 11. 明确不做

- 独立 Memory 服务、MCP server、向量数据库、embedding 模型、知识图谱；
- Markdown + JSONL + SQLite 三重主存；
- cron、自动衰减、自动归档、周期 LLM consolidation；
- 自动把 AGENTS/Session/Skill/Trellis 内容复制进数据库；
- 通过自然语言 Memory 拦截 shell/merge；
- 恢复旧 Memory Host、Coordinator、QuerySink、Dream、Learning 对象图。

## 12. 回滚

- Project Instructions 接线、Task Handoff、Memory Store/Tools、Automatic Recall 分 PR，可分别回滚。
- 回滚 Semantic Memory 只取消 FullProfile 注册并保留 `memory.sqlite3`；删除用户数据需另行授权。
- 回滚 Handoff 不改变旧 Session 读取；已写入的 `BranchSummaryEntry` 仍由现有 canonical replay 支持。
- Session、Compaction、Checkpoint 和 Plan schema 不因 Semantic Memory 改变。
