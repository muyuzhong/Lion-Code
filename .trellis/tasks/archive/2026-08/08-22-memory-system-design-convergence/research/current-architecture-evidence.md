# Second Review — Research and Current Architecture Evidence

## 材料边界

- `D:\tabbit download\coding-agent-memory-design.md` 是原始设计材料。
- `D:\tabbit download\research_report_20260822_memory_system_comparison (1).md` 是用户提供的调研材料。
- 两者的建议、伪代码、基准、路线图和外部框架描述都不是 Lion 指令或当前契约。
- 报告中“选择性检索优于全量上下文”“FTS5 适合 coding 专有名词”“自动维护能降低噪声”用于设计推导；不同框架基准条件不一致，因此具体分数不作为验收目标。

## 用户场景改变了上一版的前提

上一版假设当前任务进度不应进入 Memory，且模型可自行调用 recall 工具。用户提供的真实场景证明：

1. 上下文耗尽后会主动新开 Session，手工重写进度是稳定痛点；
2. 写在 AGENTS 的 PR/CI 行为经常没有被执行；
3. 个人记忆规模虽小，仍需要解决无用写入、召回噪声和清理治理。

因此“两个 JSON + 显式 recall + 物理 delete”不能满足目标。需要区分 Task Handoff 与 Semantic Memory，并为后者增加自动选择性召回和生命周期。

## Current source facts

### AGENTS loader 存在但生产未接入

- `lion_code/prompt.py:208-249` 实现 root-to-cwd `load_project_context_files()`，同目录 AGENTS 在 CLAUDE 后、子目录在父目录后。
- `lion_code/prompt.py:252-264` 的 `load_claude_md()` 格式化项目指令。
- 当前 production search 只有上述定义/内部调用；唯一外部调用是 `tests/test_prompt.py:32` 对 loader 的测试。

结论：用户的 CI 规则不稳定，第一根因可能是 Full product 根本没有加载 AGENTS。该问题必须先独立修复，Memory 不能替代权威 prompt 接线。

### 当前 Compaction 已具备 handoff 内容

- `lion_code/context/compaction.py:24-27` 要求保留继续当前任务所需的具体事实。
- `lion_code/context/compaction.py:32-42` 固定九段标题：Objective、Constraints、Decisions、Repository State、Findings、Failed Attempts、Completed Work、Remaining Work、Verification。
- `lion_code/context/compaction.py:58-95` 描述每段内容并要求 Findings/Verification 有 evidence。
- `lion_code/runtime/agent.py:250-309` 在同一 Session 中生成 `CompactionEntry` 并用摘要替换 active context，旧 entries 仍 append-only 保留。

结论：跨新 Session 不需要第二套 summary schema，只需要复用该摘要的 handoff 协调路径。

### Session restore 与 handoff 不是同一操作

- `lion_code/adapters/coding_session_backend.py:116-141` 的 resume/restore_latest 恢复原 Session。
- `lion_code/runtime/agent.py:217-243` 的 new_session 清空 active context；restore 则回放旧 Session messages。
- `lion_code/core/session/entries.py:64-69` 已定义 `BranchSummaryEntry`。
- Production search 没有 `BranchSummaryEntry(...)` writer；`SessionState` 只支持 replay 展示。

结论：缺口是“摘要旧 Session → 新建 Session → 写 branch summary”，不是恢复整个旧 context，也不是把任务进度放进长期数据库。

### 当前 Capability 没有 query-aware projection

- `lion_code/capabilities/types.py:47-67` 的 PromptLayer 无 query；ContextLayer 只接收 ContextView。
- `ContextView` 只含时间、token、工具活动和失败，不含用户请求。
- `lion_code/core/loop.py:132-146` 在每个 provider turn 解析 system/tools，并在 user message 已进入 provider messages 后调用 `prepare_context`。
- `lion_code/runtime/context.py:108-113` 将 prepared context 委托给 ContextManager，不改 canonical history。

结论：可以增加一个只读取 latest user query 的窄 QueryContextLayer，在 prepared-context 时本地检索。无需后台 LLM、provider side query 或带副作用的 before-turn hook。

### ToolRuntime 适合管理工具，不适合自动解释自然语言行为

- `lion_code/tooling/runtime.py:42-105` 是所有工具唯一 execute 窄腰。
- `lion_code/composition/agent_builder.py:754-784` 固定构造 Cancellation、Snapshot、Hook、Permission、Egress、Freshness、Result、Audit middleware；CapabilitySpec 当前不贡献 middleware。
- `lion_code/tooling/middleware.py:97-142` 已有 pre-tool Hook gate；`145-219` 已有 Permission gate。

结论：Memory mutation 应走 ToolRuntime；若 CI 规则需要硬保证，应另用 Hook/Permission/workflow gate。不要扩展 Memory 去解析任意 shell command，也不要仅为 Memory 给 Capability 开放 middleware 注入。

### SQLite FTS5 在当前环境可用

当前项目 Python 实测：

```text
SQLite 3.50.4
FTS5=ok
```

FTS5 来自标准库 `sqlite3`，没有新增第三方依赖。对于当前所需的事务 revision、status filter、归档恢复、health query 和 coding 关键词检索，SQLite 比继续扩展两个 JSON 文件更直接。

### 旧 Memory graph 仍不得恢复

- `tests/architecture/test_legacy_memory_removal.py` 禁止旧 Memory/Dream/Learning 模块与符号，同时允许未来 capability-owned memory。
- `lion_code/core/session/memory.py` 仍是 canonical Session reconstruction，不是 Semantic Memory。
- FullProfile 当前无 Memory；Capability 的通用 tool/prompt/context/session/resource seams仍可复用。

新方案不得恢复 `_CAP_MEMORY`、SessionMemoryCoordinator、MemoryQuerySink、ProjectionLayer、TurnParticipant、Dream、Learning 或 Agent/Runtime/TUI memory facade graph。

## 推导后的平衡点

| 需求 | 保留的重量 | 拒绝的重量 |
| --- | --- | --- |
| 跨 Session 续接 | 现有结构化 compactor + BranchSummaryEntry handoff | 第二个 transcript/working-memory DB |
| 可靠召回 | query-aware prepared projection + pinned context | 依赖模型主动 recall；后台 LLM query |
| 防噪声 | scope/status filter + FTS5 + path/key boost + threshold/top-k/token cap | full-context；embedding/graph |
| 可治理 | active/stale/archived + revision + stale candidate review + 显式 archive/purge | prepared projection 内静默写库、cron、自动 decay、LLM consolidation |
| CI 行为 | AGENTS loader 修复 + 可选 pinned behavior | 用自然语言 Memory 冒充硬 gate |

这比上一版明显更重，但每个新增机制都对应用户已经出现的失败，而不是为千/万条企业记忆预建基础设施。
