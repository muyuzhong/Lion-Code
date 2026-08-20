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

### R2. Bound recent context for compaction

- `CompactionRequest` 不再携带 `tuple[AgentMessage, ...]` 的 `recent_context`，改为只读、
  有硬上限的 `recent_context_hint: str`。
- old prefix 仍是唯一待压缩的 `history`；retained suffix 只在 request 创建前用于解析目标和
  构造 hint，既不完整进入 Provider 请求，也不写入 `CompactionEntry`。
- hint 只保留继续当前局面需要的有限信息：最近 assistant 结论、最近失败工具名和最近文件路径；
  不复制完整 ToolResult、traceback、任意工具参数或整个消息 JSON。
- hint 上限为按现有 4 chars/token 估算的 effective window 5%。threshold/manual/overflow
  共用这一条规则，不增加第二个固定阈值、reason-specific 策略或配置。
- overflow 回归必须证明 compactor Provider 输入不含 retained suffix 的大块原文，并在大
  suffix fixture 下显著小于触发 overflow 的原 context。

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
- [ ] `CompactionRequest.recent_context_hint` 是字符串且满足 effective window 5% 的硬上限；
      Provider 请求不包含 retained suffix 的完整消息或大块 ToolResult。
- [ ] overflow 集成测试证明 compaction 输入显著小于构造的 overflowing context，成功后仍只
      替换 old prefix 并保留最近两轮。
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
- 不新增可配置预算、Provider-specific tokenizer、第二套 overflow compactor 或多阶段摘要。
- 不改变状态栏 UI 风格、Git 命令策略、ContextLayer SPI 或 CapabilityRegistry 所有权。
