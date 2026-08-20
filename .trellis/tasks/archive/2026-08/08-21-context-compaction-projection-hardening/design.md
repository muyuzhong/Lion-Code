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

## 2. Bounded compaction Provider input

请求契约收敛为已预算的 provider-only 快照：

```python
@dataclass(frozen=True, slots=True)
class CompactionRequest:
    history_projection: str
    objective: str | None
    recent_context_hint: str
    input_budget_tokens: int
```

`AgentRuntime` 继续拥有 old prefix / retained suffix 的 canonical 边界切分；
`ContextRuntime.summarize()` 临时接收两段消息，解析 objective、构造 hint 和 history
projection，然后丢弃 raw messages。Request、compactor 和 Session 均不保存 message tuples。

### 2.1 Total budget and allocation

复用 `ContextPolicy.auto_compact_ratio == 0.85`：

```text
compaction_input_budget = floor(effective_window_tokens * 0.85)
objective_budget        = floor(compaction_input_budget * 0.05)
hint_budget             = floor(compaction_input_budget * 0.05)
history_budget          = compaction_input_budget
                          - estimated(system + fixed prompt)
                          - estimated(objective)
                          - estimated(hint)
```

objective 与 hint 都用现有 head/tail 字符预算语义收紧；hint 通过一次反向扫描收集最后一个非空
assistant 结论、最近失败工具名和最近 `file_path` / `path`。空值渲染 `(none)`。

最终 invariant 直接绑定实际 Provider 输入，而不是分别信任各 reserve：

```text
estimate_text_tokens(summary_system_prompt)
+ estimate_messages_tokens(provider_messages)
<= request.input_budget_tokens
```

`estimate_text_tokens()` 与现有 `estimate_messages_tokens()` 共用
`APPROXIMATE_CHARS_PER_TOKEN = 4`，不引入 tokenizer 或配置层。

### 2.2 Deterministic history projection

1. 按 canonical 顺序把 old prefix 渲染为带 role delimiter 的普通文本；不修改输入对象。
2. 若全文在 `history_budget` 内，完整保留。
3. 若超限，复用现有 `_budget_text` 的对称 head/tail 规则：保留最早背景和最新 old-history
   结尾，中段替换为包含 omitted char count 的 marker。
4. 把 history projection、objective、hint 和固定协议渲染成最终 UserMessage 后重新估算；若
   JSON/message overhead 仍使总量超限，以二分方式继续缩短 history projection，直至满足
   invariant。若 history budget 为零，使用空 history + omitted marker。
5. 如果 system + fixed prompt 单独已超过总预算，抛现有 `RuntimeError` 且不调用 Provider。

Provider compactor 在 `stream_response()` 前执行最后一次 invariant assertion，禁止任何调用方
绕过预算。overflow 仍保留最近两个 user boundaries、只替换 old prefix；Application 的
compact-once/retry-once 流程不变。

该最小投影会省略 old history 中段，但 canonical/append-only JSONL 不被投影改写。分段或
hierarchical compaction 需要多次 Provider 调用、失败恢复和中间摘要契约，本任务不预建；只有
评测证明 head/tail 丢失了继续任务所需信息时再单独设计。

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
| empty objective/hint | render marker / `(none)` |
| objective/hint exceeds its 5% reserve | deterministic head/tail truncation |
| history exceeds remaining total budget | deterministic head/tail projection + omitted marker |
| fixed prompt exceeds total budget | fail before Provider; no CompactionEntry |
| final serialized input exceeds budget | shrink history again; never send oversized input |
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
