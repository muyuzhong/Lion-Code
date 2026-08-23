# Lion Memory 实现验收报告

## 结论

**不通过验收。** 当前 `origin/master` 的实现质量并非普遍失控：定向测试全部通过，四象限隔离、事务、prepared-only 投影和旧 Memory 对象图隔离都有证据。但它实现的是后来归档的“Session handoff + FTS/revision/stale + query-aware 自动召回”方案，而不是用户最后确认的 `6c9fddd` 一期方案。

阻断点不是局部 bug，而是产品状态模型错位：当前产品没有 Task Ledger 和 `recall_tasks`，因此干净新 Session 无法按需知道项目有哪些未完成任务；与此同时，已经进入 review 的旧记忆仍会被自动注入，直接击中“回想引入噪声、清理治理失效”的核心风险。

审查锚点：

- 最终产品契约：`6c9fdddc3a7957898c74d6b18a0879ac298121fb`
- 当前产品树：`origin/master = e01be42c6ceeb3119e784c301b295e5d8e64575d`
- 当前实现提交线：PR #89 `ee10c13`、PR #90 `d6be834`、PR #92 `5a4b318`、PR #93 `ddb0c20`
- 归档 PRD 只用于解释当前实现来源，不覆盖 `6c9fddd`

## Findings

### [P1] Task Ledger 与 MemoryPolicy 缺失，核心的“干净会话按需续接任务”不可实现

**影响：** 用户在新 Session 询问“有哪些未完成任务”或“继续任务”时，没有持久任务目标、摘要、下一步和 refs 可供查询；只能手工回忆、检查 Git/代码，或使用只针对当前 Session 的 handoff。这与用户明确区分的“连续任务之间按需找回任务”不是同一能力。

**触发：** 在任务 A/B 已由 Agent 推进后开启干净新 Session，并要求列出当前项目 open tasks。

**证据：**

- `lion_code/capabilities/memory/store.py:59-112` 只建立 `memory_meta`、`memory_entries`、唯一索引和 `memory_fts`，没有 `tasks` 表。
- `lion_code/capabilities/memory/capability.py:137-149` 只注册五个 Semantic Memory 工具，没有 `remember_task` / `recall_tasks`。
- `lion_code/capabilities/memory/capability.py:637-652` 创建的 Capability 只有 tool source 与 QueryContextLayer，没有 MemoryPolicy PromptLayer。
- `lion_code/runtime/agent.py:228-260` 的 `handoff_session` 是把当前 canonical Session 压缩后切换到新 Session，解决的是同一任务换会话，不保存或枚举项目任务。
- 全仓搜索 `recall_tasks|remember_task|CREATE TABLE tasks|Task Ledger` 在生产代码与 Memory 测试中无命中。

**基线：** `6c9fddd` 的 `design.md:7-17,137-167` 明确要求 Task Ledger、`remember_task`、`recall_tasks` 与 MemoryPolicy；`prd.md:20,95,122,140` 明确拒绝用 Session handoff 替代该能力。

**测试缺口：** `tests/capabilities/test_memory_capability.py:130-140` 反而断言工具集合恰好只有这五个旧工具；`tests/integration/test_session_handoff.py` 验证的是被最终方案列为 out of scope 的 handoff，因此全部通过仍不能证明核心目标。

### [P1] `needs_review` 只是报告标签，过期或路径失效记忆仍进入自动召回

**影响：** 已超过复核周期的历史行为/事实会持续注入；pinned 条目即使全部路径已失效也照常注入，多路径 relevant 条目只要还剩一个路径存在也会继续被认为健康。系统能“发现”问题，却没有把问题记忆从召回面隔离，无法达到低噪声治理目标。

**触发：** pinned 条目的 `validated_at` 超过 90 天，或其多个项目路径中任一失效。

**证据：**

- `lion_code/capabilities/memory/store.py:743-753` 的 `pinned()` 只检查 `active + recall_mode=pinned`，不检查验证时间或动态 review。
- `lion_code/capabilities/memory/store.py:759-789` 只把过期条目列到 `long_unvalidated`；QueryContextLayer 不消费这个结果。
- `lion_code/capabilities/memory/store.py:885-910` 只有“全部 path 失效”才剔除，部分失效仍进入 healthy。
- `lion_code/capabilities/memory/query_layer.py:112-134` 直接注入 pinned，只有 relevant 才执行 path partition。
- 最小复现得到 `reported_long_unvalidated=['old-rule']`，同时 `still_auto_injected=True`；全部路径失效的 pinned 同时出现在 review candidate 和自动注入中；部分路径复现得到 `partial_missing_kept=['partial-path']`、`candidates=[]`。

**根因：** 当前实现沿用旧 PRD 的 persisted `active|stale|archived` 与“全部路径失效”规则，没有实现最终方案的读取时 `needs_review = age expired OR 任一路径不存在` 过滤。

**基线：** `6c9fddd design.md:200-218` 要求 needs-review 条目同时退出 pinned 和 active recall；`prd.md:85-88,130` 要求动态计算且不持久化 stale/review。

**测试缺口：** `tests/capabilities/test_memory_store.py:608-616` 明确把“部分路径失效不进入 candidate”固化为正确行为；过期测试只检查 review 列表，没有断言 query/pinned 排除。

### [P2] 权限工具拆分和 pinned 生命周期与批准契约相反

**影响：** 模型无法在主循环中无打扰地维护普通任务/非 pinned 语义记忆，因为所有 remember 与 manage 都要求确认；另一方面，archive/restore 会保留 `recall_mode=pinned`，一次 restore 会让旧内容立即重新进入自动注入，不需要明确的重新 pin 意图。

**触发：** 普通 semantic remember、可逆 archive/restore/validate，或恢复曾经 pinned 的 archived 条目。

**证据：**

- `lion_code/capabilities/memory/capability.py:342-344,424-426,616-618` 为两个 remember 和整个 manage 工具统一设置 `requires_confirmation=True`。
- `lion_code/capabilities/memory/capability.py:543-618` 把可逆动作和不可逆 purge 放在同一个固定权限工具里，无法按 action 表达契约。
- `lion_code/capabilities/memory/store.py:565-589,641-658` 改 status 时不清除 `recall_mode`，restore 直接回到 active。
- 最小复现显示 `archived_recall_mode=pinned`、`restored_recall_mode=pinned`，随后 `s.pinned()` 立即返回该条目。

**基线：** `6c9fddd design.md:133-153` 要求普通 remember/manage 无确认，单独的 `set_memory_pinned` 与 `purge_memory` 才确认；archive 清 pin，restore 保持非 pinned。`prd.md:76-79,127-128` 给出相同验收条件。

**测试缺口：** `tests/capabilities/test_memory_capability.py:152-161` 将所有 mutation 都需确认固化为预期；现有 restore 测试只断言 status/FTS，不断言恢复后不得自动注入。

### [P2] Evidence/validate/stable-key 治理约束不足，条目可以被伪刷新或重复创建

**影响：** 任意非空字符串（如 `"e"`、`"anything"`）都能成为 evidence；`validate` 不要求 evidence 即可刷新时间；首尾空格变体还能绕过 stable-key 唯一性。这会让错误或不可复核条目看起来已验证，并产生两个逻辑同 key 的 active 条目。

**触发：** remember 传入任意字符串列表，或对条目调用 `manage_memory(action="validate")` 而不提供新证据，或依次写入 `dup` 与 ` dup `。

**证据：**

- `lion_code/capabilities/memory/store.py:79-82,145-165` 将 evidence 存为无类型字符串数组。
- `lion_code/capabilities/memory/store.py:489-500` 只检查列表非空和字符串非空。
- `lion_code/capabilities/memory/store.py:628-636` 的 validate 只更新 `validated_at/updated_at`。
- `lion_code/capabilities/memory/capability.py:596-613` 的 manage schema 没有 evidence 参数。
- `lion_code/capabilities/memory/store.py:72,495-500` 只用 `trim()` 检查非空，没有规范化后再存储或比较 stable key。
- 最小复现显示 `arbitrary_evidence=('anything',)` 可写入，`validate_without_new_evidence=True`，并且 `dup` 与 ` dup ` 同时为 active。

**基线：** `6c9fddd design.md:112-129,217` 只允许 `user_request|source|test|command` + 非空 reference，并要求 validate 携带新 evidence。

**测试缺口：** 现有测试只拒绝 evidence 的 JSON 类型错误/空字符串，并大量以 `["e"]` 作为有效夹具；validate 测试只检查时间变新。

### [P2] archived 条目无法通过模型工具重新列出，restore 实际依赖记住旧 ID

**影响：** archive 后条目退出 FTS；review 只返回数量而不返回 archived id。新 Session 中模型若没有保留旧 id，就无法发现和 restore 已归档内容，治理入口不闭环。

**触发：** 归档任意 Semantic Memory，随后在不知道原始 `m:<id>` 的会话中尝试查找或恢复。

**证据：**

- `lion_code/capabilities/memory/store.py:561-583` 在 archived 时删除 FTS 行且不重建。
- `lion_code/capabilities/memory/store.py:678-711` 的 `include_inactive` 仍从 FTS join，因此无法返回已退出索引的 archived 条目。
- `lion_code/capabilities/memory/store.py:759-794` 的 review 只保存 `archived_count`，没有 archived entries。
- `lion_code/capabilities/memory/capability.py:453-503` 的模型可见 review 输出同样没有 archived id 列表。
- 最小复现结果为 `include_inactive_hits=[]`、`archived_count=1`。

**基线：** `6c9fddd prd.md:88,131` 与 `design.md:211` 要求显式 archived view 返回可用于 restore 的 id，普通 recall 不开放 inactive 参数。

**测试缺口：** 测试验证 archive 从 FTS 消失和“持有已知 id 时 restore”，没有覆盖新会话如何枚举 archived id。

### [P2] 被推迟的 FTS/query-aware 自动召回未经原型门禁直接上线，并已出现中文召回缺陷

**影响：** 中文用户用两字词查询时可能完全召回不到包含该短语的记忆。与此同时，新增通用 QueryContextLayer SPI、FTS/revision/status 维护和大规模测试，扩大了当前一期维护面。

**触发：** 中文内容中间包含查询词，例如内容“必须等待持续集成完成后才能合并”，查询“等待”。

**证据：**

- `lion_code/capabilities/memory/store.py:108-111` 建立默认 tokenizer 的 FTS5 表；`store.py:678-726` 直接使用 FTS MATCH/BM25。
- 最小复现中 `search("等待")` 返回 0。
- 全仓没有 lexical 原型、recall@5/precision@5、trigram 或两字中文实验产物。
- PR #92 增加 2,944 行，PR #93 再增加 1,439 行；其中生产 FTS/query-aware 部分属于最终一期明确后置的复杂度。

**基线：** `6c9fddd prd.md:95-96,132,143,151` 与 `design.md:220-230,247` 要求一期只做 explicit literal recall，先用离线夹具验证 tokenizer/中文短查询，再单独决定二期自动召回。

**测试缺口：** 搜索测试覆盖英文、路径、变音符和空/单字符查询，没有中文自然语言或两字 substring。

### [P2] pinned 预算存在 head-of-line blocking，超大低优先条目可使后续小条目全部消失

**影响：** 排序第一条超预算时，后续很小且本可放入预算的 pinned 行为也不会注入；系统会在“存在关键 pinned”时渲染为空。

**触发：** 第一个候选超过预算，后续候选可容纳。

**证据：** `lion_code/capabilities/memory/query_layer.py:50-64` 遇到超预算条目使用 `break`；`query_layer.py:112-121` 排序后直接复用该函数。最小复现中 3513-token 的 `a-large` 使 15-token 的 `b-small` 也被丢弃，`kept=[]`。

**基线：** `6c9fddd design.md:195` 要求逐条加入、绝不截断单条，并由 review 报告超限 id；一个超限条目不应垄断后续条目的选择机会。

**测试缺口：** 预算测试只断言总量不超限，且大条目排在后面；没有覆盖大条目排第一、后续小条目可容纳的负向场景。

### [P2] FullProfile 构造即创建用户数据库，fresh DB 并发初始化还存在竞争

**影响：** 只构造 Full Agent 就会在用户 home 下产生持久文件；损坏或旧 schema 会在 composition 阶段阻断启动。两个 Lion 实例首次同时启动时，还可能有一个因 `database is locked` 或 `table memory_meta already exists` 启动失败。后续回到批准的一期 schema 时，现有 v1 又没有迁移/兼容路径，增加了用户数据处置成本。

**触发：** 构造默认 `FullProfile()`，即使本次会话从不使用 Memory；并发竞争在两个以上实例首次指向同一个尚不存在的 DB 时出现。

**证据：**

- `lion_code/capabilities/memory/store.py:263-269,294-314` 在构造函数中立即创建目录并初始化/校验数据库。
- 初始化锁是 `MemoryStore` 实例字段；`_existing_objects()` 与 `_create_schema()` 之间没有跨实例原子边界。
- `lion_code/composition/agent_builder.py:643-655` 在 Full composition 分支直接构造 `MemoryStore(default_memory_db_path(), ...)`。
- `tests/architecture/test_composition_profiles.py:273-295` 明确断言 build 完成后 DB 已存在。
- `lion_code/capabilities/memory/store.py:67-111` 把 persisted stale、revision、supersedes 和 FTS 固化到 v1。
- 最小复现显示 `db_exists_after_constructor=True`；8 个线程并发构造同一个 fresh DB，20 轮中 8 轮至少一个实例失败，错误包含 `database is locked` 与 `table memory_meta already exists`。

**基线：** `6c9fddd prd.md:85-96,103,132` 与 `design.md:42-44` 要求首次实际 read/write 才开库，一期只有 tasks + semantic canonical 表，不建立 FTS/revision/persisted stale。

**测试缺口：** 组合测试把 eager creation 当作成功标准，没有“仅构造 Full 不创建数据库”的负向测试；并发测试均在 `setUp` 已建好 schema 后运行，没有覆盖 fresh DB 初始化竞争。

## Contract Matrix

| 最终一期契约 | 状态 | 当前证据 |
| --- | --- | --- |
| R1 一个 Capability/一个 SQLite/Task + Semantic 两模型 | **partial** | 单 Capability/单库存在；Task 模型缺失 |
| R2 项目任务按需续接 | **missing** | 无 tasks 表与 task tools；Session handoff 是另一能力 |
| R3 四象限 definition/behavior | **partial** | scope/kind/trigger/project 隔离成立；stable key 未规范化 |
| R4 受控写入与 pin 边界 | **contradicted** | 全 mutation 确认；无独立 pin/purge；restore 保留 pinned |
| R5 类型化 evidence + active/archived + 动态 review | **contradicted** | 字符串 evidence、persisted stale/revision；review 不阻断注入 |
| R6 一期 pinned + explicit literal recall；auto relevant 后置 | **contradicted** | pinned 已有；生产 FTS + QueryContextLayer 自动 relevant 已上线 |
| R7 SQLite、fail-closed、path identity、lazy open | **partial** | SQLite/隔离/fail-closed 基本存在；lazy open 与一期 schema 不符合 |
| R8 Capability ownership、MemoryPolicy、普通 ContextLayer | **partial** | store 由 capability adapters 持有且 prepared-only；无 MemoryPolicy，新增 query SPI；handoff/AGENTS 越界 |
| R9 离线 lexical 原型 | **missing** | 无夹具、指标或 go/no-go 产物 |

## Acceptance Criteria Matrix

| 最终 AC | 状态 | 说明 |
| --- | --- | --- |
| AC1 新 Session `recall_tasks` 返回 0/1/N open tasks | **missing** | 无 Task Ledger 与 task recall |
| AC2 task create/update/complete/reopen，显著变化才写 | **missing** | 无 task 工具与 MemoryPolicy |
| AC3 四象限 CRUD、归档恢复、项目隔离 | **partial** | 四象限和隔离可用；更新采用被后置的 revision 模型 |
| AC4 kind 契约 + typed evidence | **partial** | definition/behavior 约束正确；evidence type 缺失 |
| AC5 同 stable key 一个 active + restore conflict | **partial** | exact raw key 成立；空格变体可同时 active |
| AC6 默认非 pinned 无确认，仅 pin/unpin/purge 确认 | **contradicted** | 所有 mutation 均确认 |
| AC7 pinned 不可被普通 remember 改写；archive 清 pin；restore 非 pin | **contradicted** | remember 可 supersede pinned；restore 恢复 pinned |
| AC8 pinned 只注入 active、非 needs-review、有界结果 | **contradicted** | active/空块成立；needs-review 与预算选择失败 |
| AC9 path/age 动态 review，validate 携新 evidence 后恢复 | **contradicted** | review 能报告部分情况；选择层忽略 age/pinned path，validate 无 evidence |
| AC10 archived view 可找 id 并 restore | **contradicted** | 只有 count；archived 不在 FTS |
| AC11 一期无 relevant/query-aware/FTS/background | **contradicted** | 前三者存在；仅 background 不存在 |
| AC12 不自动采集 repo/AGENTS/Session/Trellis/Skill | **implemented** | 未发现 Memory 自动采集路径 |
| AC13 构造 Full 不创建 DB；故障在首次访问显式报错 | **contradicted** | 构造即创建/验证；同名 extension 可移除 Memory |
| AC14 Capability/Context/ToolRuntime/Session/旧图门禁 | **implemented** | 定向架构测试通过，projection 保持 prepared-only |
| AC15 离线 prototype 与 go/no-go | **missing** | 无产物 |

## PR 交付线判定

| 交付线 | 对最终一期的判定 |
| --- | --- |
| PR #89 AGENTS/CLAUDE loader | **out-of-scope-added**；本身可能有产品价值，但不是 Memory 一期验收项 |
| PR #90 Session handoff | **out-of-scope-added**；解决同一 Session 任务换会话，不等价于 Task Ledger |
| PR #92 SQLite Semantic Store | **partial + contract drift**；四象限/事务/隔离可复用，schema/evidence/权限/lifecycle 属于旧方案 |
| PR #93 Query-aware 自动召回 | **deferred feature shipped**；prepared-only 边界正确，但最终一期明确后置且缺实验门禁 |

## 已确认通过的边界

- 没有发现 P0 数据破坏或越权执行路径。
- long-term/current-project 的 scope 隔离和 active stable-key 唯一索引有实现与测试。
- definition/behavior 的 trigger 约束、project path 规范化、事务 rollback、schema/integrity fail-closed 有定向测试。
- Query projection 不写 canonical Session/JSONL、不调用第二个 Provider；旧 Memory/Dream/Learning 图没有恢复。
- Coding/Minimal 不默认启用 Memory；Full 可用同名 extension spec 移除内置 Memory。

这些结论说明已有代码中有可保留的工程质量，但不足以抵消核心产品契约缺失。

## 验证记录

定向测试（使用临时目录/临时 SQLite，未打开真实用户 Memory DB）：

```text
python -m pytest -q \
  tests/capabilities/test_memory_store.py \
  tests/capabilities/test_memory_capability.py \
  tests/capabilities/test_memory_query_layer.py \
  tests/context/test_query_context_layer.py \
  tests/architecture/test_memory_auto_recall.py \
  tests/architecture/test_legacy_memory_removal.py \
  tests/integration/test_session_handoff.py

132 passed in 12.69s

python -m pytest -q \
  tests/architecture/test_composition_profiles.py \
  tests/test_prompt.py

30 passed in 3.48s
```

最小复现结果：

```text
db_exists_after_constructor=True
two_char_chinese_hits=0
reported_long_unvalidated=['old-rule']
still_auto_injected=True
missing_path_pinned_injected=True review_candidates=['gone-pinned']
partial_missing_kept=['partial-path'] candidates=[]
arbitrary_evidence=('anything',)
validate_without_new_evidence=True
stable_keys=[('dup', 'active'), (' dup ', 'active')]
include_inactive_hits=[] archived_count=1
archived_recall_mode=pinned
restored_recall_mode=pinned
auto_injected_after_restore=['rule']
budget costs=[('a-large', 3513), ('b-small', 15)] kept=[]
fresh-db concurrent init: 8/20 runs had at least one constructor failure
```

## 测试有效性判断

现有测试并不是无效；它们对**旧实现契约**覆盖较强。问题在于，它们把被最终设计否决的行为当成了正确答案：五工具集合、所有 mutation 确认、部分 path 失效仍健康、eager DB、persisted stale/revision、自动 FTS 和 Session handoff。因而“162 个测试通过”证明当前实现内部一致，不能证明它符合最终产品决策。

## Residual Risks

- 本审查没有运行完整 CI/Trellis check；用户已说明此前执行过，本轮只跑与 findings 直接相关的 162 个测试。
- 没有打开真实 `~/.lion-code/memory.sqlite3`，因此未评估真实数据量、已有条目质量或用户数据迁移成本。
- 没有调用真实 Provider；MemoryPolicy 缺失的实际工具调用率只能作为产品风险，不能从本轮静态审查量化。
- 当前架构 spec 已同步成旧实现（例如 query-aware auto-recall 与 handoff），它们与 `6c9fddd` 冲突；若后续只按现行 spec 开发，偏差会继续被固化。

## 验收建议

在修复前不要把当前实现标记为“最终设计已完成”。后续应单独授权收敛实现，优先级为：

1. 先建立 Task Ledger、task tools 与 MemoryPolicy，完成核心任务续接闭环；
2. 将 lifecycle/evidence/pin 权限改回最终契约，让动态 needs-review 真正退出召回面，并补齐可枚举的 archived view；
3. 移除或默认关闭一期外的 handoff/QueryContext/FTS/revision 复杂度；自动 relevant recall 只有在离线中文/负样本实验过线后再进入二期；
4. 恢复 lazy DB initialization，并补充“构造 Full 无持久副作用”的验收测试。

本报告只给出审查结论，未修改任何产品代码、测试或架构规范。
