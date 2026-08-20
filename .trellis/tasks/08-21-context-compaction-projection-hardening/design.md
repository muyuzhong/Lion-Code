# Context Compaction and Projection Hardening — Technical Design

## 1. Boundary correction

本次直接删除单实现 Feature protocol，不用另一个抽象替换它：

```text
Before: Composition -> ContextRuntime._plan_view -> PlanRuntime
After:  Composition -> ContextRuntime -> generic CompactionRequest
```

`resolve_compaction_objective()` 只接收 `requested_objective`、old `history` 和 retained
`recent_context`。它不再读取文件或任何 Capability view。Composition 删除
`plan_view=foundation.plan`，`ContextRuntime.__init__` 删除对应参数和字段。

回归保护放在现有架构测试中：FullProfile 对象图断言 `ContextRuntime` 不可达
`PlanRuntime`；AST gate 精确禁止 `CompactionPlanView`、`_read_active_plan`、`_plan_view`
和 ContextRuntime 构造时的 `foundation.plan` 接线。门禁只绑定这次删除的 coupling，不做
“Plan”全文禁词。

## 2. Bounded compaction request

请求契约收敛为：

```python
@dataclass(frozen=True, slots=True)
class CompactionRequest:
    history: tuple[AgentMessage, ...]
    objective: str | None = None
    recent_context_hint: str = ""
```

`AgentRuntime` 继续拥有 old prefix / retained suffix 的边界切分；`ContextRuntime.summarize()`
临时接收 suffix，按 generic message 内容解析 objective 并构造 hint，然后丢弃 suffix。
`ProviderContextCompactor` 只 deep-copy `request.history`，追加包含 objective、hint 和固定协议的
一条 prompt message。Request、compactor 和 Session 均不保存 retained messages。

Hint 使用一次反向线性扫描构造，在预算耗尽时立即停止，只收集：

- 最后一个非空 assistant 文本结论；
- 最近失败的 `ToolResultMessage.tool_name`；
- 最近 ToolCall 中 `file_path` / `path` 的字符串值。

整段 hint 最终截断到：

```text
effective_window_tokens * 5% * 4 chars/token
```

实现复用仓库当前 4 chars/token 估算常量，不引入 tokenizer、配置或 reason-specific 分支。
objective 独立传递，不在 hint 中重复。空 hint 渲染 `(none)`。

这使 Provider compaction 输入从 `history + full suffix + prompt` 变成
`history + bounded hint + prompt`。overflow 仍保留最近两个 user boundaries 并只替换 old
prefix；Application 的 compact-once/retry-once 流程不变。

## 3. Structured summary validation

`compaction.py` 维护唯一的九 heading tuple，prompt 测试和 validator 共用该顺序。
Provider 返回非空文本后，validator 按完整行匹配 heading，并检查：

1. 每个 required heading 恰好一次；
2. 九个 required heading 的行号严格递增。

不检查 section 正文、Evidence 语法或额外普通文本。失败抛
`InvalidCompactionSummary(RuntimeError)`。校验位于 `ProviderContextCompactor.summarize()`
返回之前；既有 `AgentRuntime.summarize -> record_compaction` 顺序自然保证失败不落盘，
无需事务、恢复分支或 fallback。

## 4. Bounded ContextView and layers

`ContextView.from_messages()` 仍从 canonical messages 派生一次只读快照，但快照只保留：

```text
tool totals       <= 3 rows (overflow merged into other)
repeated details  <= 3 rows
recent details    <= 3 rows
recent failures   <= 3 rows (unchanged)
```

四处列表共用一个 `N=3` 常量。内部可用一个最小 counted-activity value 表达
`label + count`；不保留兼容的全量
`tool_trace` alias。统计值随 view 创建，不存入 ContextManager/Capability/Session，不形成新的
mutable owner。相同 count 时使用首次出现顺序，recent 使用消息顺序；渲染顺序确定。

`AgentStateLayer` 输出 per-tool totals，再输出去重后的 top repeated/recent 明细。无活动时仍显示
`none`。单条 argument 摘要与 failure 摘要继续使用现有 240 字符边界。

`GitStatusLayer` 保持每次执行现有两个 Git 命令。`_status_paths()` 继续负责 rename 目标和排序；
renderer 只展示总数和前三个路径，超出时追加 `- ... N more`。不缓存 Git 状态。

## 5. Error and persistence matrix

| Condition | Result |
| --- | --- |
| no explicit/recent/history objective | marker only; never read Plan |
| empty hint | render `(none)` |
| hint exceeds budget | deterministic truncation; no raw suffix fallback |
| Provider error / empty summary | existing compaction RuntimeError |
| missing/duplicate/out-of-order headings | `InvalidCompactionSummary` |
| validation/cancellation failure | no CompactionEntry; canonical history unchanged |
| no tools / clean Git | bounded `none` / `clean` output |

## 6. Rollback and scope

代码改动限制在 compaction contract/runtime wiring、ContextView/两个内置 ContextLayer、相应
测试和 runtime-boundaries spec。无需数据迁移；`CompactionEntry` 仍保存普通 summary 字符串。
每个修复提交都可通过回退其代码、测试和同提交 spec 片段恢复，不触碰 Session JSONL。

明确不实现 `CompactionContributor`、strict Evidence parser、可配置预算、第二压缩器或持久化
activity counter。
