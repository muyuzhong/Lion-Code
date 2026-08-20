# Context Compaction and Projection Hardening

## Goal

修复当前 Context Engineering 的四个已确认回退：移除 Plan 对 Context Kernel / Runtime
的语义依赖，保证 overflow compaction 不再把保留后缀完整拼回 Provider 请求，为九段式摘要
增加最小结构校验，并把 Agent/Git 瞬态状态输出限制为与历史长度无关的固定上界。

## Confirmed repository facts

- `lion_code/context/compaction.py:70-77,190-204` 定义 `CompactionPlanView` 并读取
  Plan 文件；`lion_code/runtime/context.py:43-50,144-149` 持有 `_plan_view`，Composition
  又在 `lion_code/composition/agent_builder.py:285-296` 直接传入 `foundation.plan`。虽然没有
  具体类 import，当前真实对象图仍是 `ContextRuntime -> PlanRuntime`。
- `lion_code/runtime/agent.py:270-292` 把 canonical messages 拆成 old prefix 与 retained
  suffix；`lion_code/context/compaction.py:113-116,160-176` 随后把整个 suffix 文本化并追加
  到 old prefix 后发给 Provider。`compact_for_overflow()` 在
  `lion_code/runtime/agent.py:311-318` 保留两个 user boundaries，因此可能重建接近原请求
  大小的压缩输入。
- `ProviderContextCompactor.summarize()` 在 `lion_code/context/compaction.py:124-132` 只拒绝
  Provider error 和空文本，没有验证九个 heading。`AgentRuntime` 在
  `lion_code/runtime/agent.py:288-296` 先等待 summary，之后才写 `CompactionEntry`，已经具备
  “校验失败不落盘、原历史不替换”的正确调用顺序。
- `ContextView.from_messages()` 在 `lion_code/context/types.py:157-165` 保存全部 tool traces；
  `AgentStateLayer` 在 `lion_code/capabilities/agent_state/capability.py:43-62` 渲染全部不同
  调用。`GitStatusLayer` 在 `lion_code/capabilities/git_status/capability.py:20-32` 渲染全部
  dirty paths。两者输出都随历史或工作区规模增长。
- `recent_failures` 已在 `lion_code/context/types.py:166-170` 限制为最近三条，应保持不变。
- 当前分支从最新 `origin/master` 创建；创建前已验证旧 feature branch 与
  `origin/master` tree 相同。工作区另有用户未跟踪文件 `after1.tmp`，不属于本任务。

## Requirements

### R1. Restore the generic Context boundary

- 删除 `CompactionPlanView`、`_read_active_plan()`、`ContextRuntime.plan_view/_plan_view` 以及
  Composition 的 `plan_view=foundation.plan` 接线。
- compaction objective 只按以下顺序解析：显式当前用户目标 → retained suffix 中最近用户目标
  → old history 中最近用户目标；无可靠目标时保持 `None` 并使用既有 unavailable marker。
- 增加架构回归门禁，证明 FullProfile 的 `ContextRuntime` 不可达 `PlanRuntime`，并绑定本次
  删除的 Plan-compaction coupling symbols。

### R2. Bound the complete compaction Provider input

- 总预算为 `effective_window_tokens * 0.85`，复用现有 auto-compaction 安全比例，不增加新
  配置。最终 Provider 输入必须满足：

  `estimated(system + fixed prompt + objective + hint + history projection)
  <= compaction_input_budget`。
- fixed/system prompt 按实际静态文本预留；objective 与 hint 各自最多占总预算 5%；old
  history projection 只能使用剩余预算。预算计算继续复用现有 4 chars/token estimator。
- `CompactionRequest` 不再携带 raw `history` 或 `recent_context` message tuples，只携带
  `history_projection: str`、bounded objective、`recent_context_hint: str` 和
  `input_budget_tokens`，因此 request 本身就是发往 compactor 的有界只读快照。
- retained suffix 只在 request 创建前用于解析目标和构造 hint。hint 只保留最近 assistant
  结论、最近失败工具名和最近文件路径，不复制完整 ToolResult、traceback、任意工具参数或
  整个消息 JSON。
- old prefix 先按 role/source order 渲染为 provider-only 文本；超过 history 剩余预算时，
  使用现有 head/tail budget 语义保留开头和最近结尾，并插入明确的 omitted marker。最终按
  序列化后的 Provider messages 重新估算并收紧，直到满足总预算；canonical history 不改写。
- 如果 fixed prompt 本身已经超过总预算，压缩在调用 Provider 前以现有 `RuntimeError` 失败，
  不发送已知超限请求，不写 `CompactionEntry`。threshold/manual/overflow 共用同一规则。
- overflow 回归必须证明 compactor Provider 输入满足总预算、显著小于触发 overflow 的原
  context，并且 oversized history 不会原样进入 Provider 请求。

### R3. Enforce the nine-section summary contract

- 对 Provider 返回文本执行轻量校验：九个规定 heading 必须各出现一次且顺序正确。
- 非法输出抛出专用 `InvalidCompactionSummary`；不做自动修复、重试、fallback summary 或
  Evidence 内容解析。
- 校验发生在 compactor 返回前，因此失败时不得追加 `CompactionEntry`、不得替换 canonical
  history，并保留现有 Provider error / empty summary / cancellation 行为。

### R4. Bound ephemeral status output

- `ContextView` 不再保存全部 tool traces，只保留固定上限的 per-tool totals、重复调用摘要和
  最近调用摘要；`AgentStateLayer` 只渲染这些有界投影。
- 复用一个固定 `N=3`：最多 3 个 tool totals、3 个高频重复摘要、3 个最近摘要；超出 tool
  totals 的调用合并为 `other`，不新增配置项或 mutable counter owner。
- Git 状态显示 dirty file 总数，只列前三个稳定排序路径，其余显示 `... N more`。
- 保持每条 argument/failure 摘要的现有字符上限、最近三条 failure、prepared-only 语义和
  每次 render 实时读取 Git 的行为。

### R5. Preserve existing ownership and persistence

- 不改 ContextPolicy 阈值、protected-window 边界、overflow 单次重试策略、Provider SDK、
  AgentHarness、Session entry/schema/replay 或 canonical history 所有权。
- 不新增 Capability compaction extension、`CompactionContributor`、Memory/Plan/Todo 替代层、
  兼容别名、fallback 或持久化状态。
- 更新 `.trellis/spec/backend/runtime-boundaries.md` 中已合并但错误的 Plan contribution、
  unbounded recent context 与 prompt-only structure 描述，使规范与修复后对象图一致。

## Acceptance Criteria

- [ ] `ContextRuntime`、Context Kernel 和 compaction request 不持有或读取 Plan；FullProfile
      reachable-object-graph 与精确 coupling gate 均通过。
- [ ] explicit → recent user → history user → unavailable 的 objective 顺序有直接测试。
- [ ] 每个 compaction Provider 调用均满足
      `estimated(total input) <= effective_window_tokens * 0.85`；objective/hint 各不超过
      总预算 5%，Provider 请求不包含 raw history/suffix message tuple 或大块 ToolResult。
- [ ] oversized history 投影确定性保留 head/tail 与 omitted marker，final serialized input
      仍在预算内，输入 canonical history 逐条不变。
- [ ] overflow 集成测试证明 compaction 输入满足总预算并显著小于构造的 overflowing
      context，成功后仍只替换 old prefix 并保留最近两轮。
- [ ] 九个 heading 缺失、重复或乱序均抛 `InvalidCompactionSummary`；合法摘要仍可写入并
      replay；非法摘要不新增 `CompactionEntry` 且原 history 不变。
- [ ] 长工具历史生成的 `ContextView` 与 AgentState 输出满足 3/3/3 上限，同时保留准确的
      per-tool 总调用数、最近三条失败和确定性顺序。
- [ ] Git dirty files 为 0、3、超过 3 三种情况均按总数 + 前三项 + `... N more` 渲染，
      每次 render 仍重新读取工作区。
- [ ] 聚焦测试、架构测试、全量测试和适用 CI 质量门禁通过；若仓库基线有噪声，单独报告且
      不掩盖本任务新增违规。
- [ ] 只提交任务代码、测试、Trellis/spec 文件，保留 `after1.tmp` 和其他无关工作区内容。

## Out of scope

- 现在不设计或注册 `CompactionContributor`；只有至少两个 Capability 出现真实、已批准的
  compaction contribution 需求时再规划该通用 SPI。
- 不解析每个 summary section 的正文或 Coding Evidence，不增加 schema/JSON 输出。
- 不新增可配置预算、Provider-specific tokenizer、第二套 overflow compactor、分段调用或
  多阶段摘要；只有评测证明 head/tail 投影丢失了必要信息时再单独规划 hierarchical compaction。
- 不改变状态栏 UI 风格、Git 命令策略、ContextLayer SPI 或 CapabilityRegistry 所有权。
