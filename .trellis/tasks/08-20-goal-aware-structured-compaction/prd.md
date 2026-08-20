# Goal-Aware Structured Compaction

## Goal

将已有全局上下文预算系统的 compaction 产物升级为目标感知、固定结构且可追溯的
工作摘要，使下一次模型调用能围绕当前任务继续工作，并能从摘要中的 Coding
Evidence 回到源码、测试、提交或错误依据。压缩阈值、裁剪策略、canonical history
和 append-only Session 语义保持不变。

## Background and confirmed repository facts

- `lion_code/context/compaction.py::ContextCompactor` 当前契约是
  `summarize(tuple[AgentMessage, ...]) -> str`；`ProviderContextCompactor` 复制旧消息，
  追加 `SUMMARY_USER_PROMPT`，再通过 `ModelProvider.stream_response()` 获取摘要。
- `lion_code/runtime/context.py::ContextRuntime.summarize` 是运行时 compactor 的唯一
  调用包装点；`lion_code/runtime/agent.py::AgentRuntime.compact_if_needed` 在
  `agent.py::269-285` 计算旧历史边界并目前只传递待压缩历史。
- `ContextPolicy` 当前常量为 `0.50 / 0.60 / 0.70 / 0.75 / 0.85`，分别对应 large
  tool-result budget、stale-result snip、aggressive budget、hot-cache override 和
  whole-history compaction；`ContextManager._protected_result_indexes` 保留最近 3 个
  eligible tool results 及每个文件最后一次 `read_file`。
- `ContextManager.prepare()` 通过深拷贝生成 provider projection；它不改写 canonical
  messages、Session JSONL 或 CompactionEntry。prepared-only `<agent-state>` 也不进入
  compactor 输入。
- `CompactionEntry` 位于 `lion_code/core/session/entries.py::CompactionEntry`，只保存
  `summary` 与 `replaces_entry_ids`；`SessionRecorder.record_compaction()` 在现有
  append-only 链上追加该 Entry，并由 `SessionState.from_entries()` 回放为摘要消息。
- `PlanView` 只提供 `is_active` 和 `file_path`；激活时 Plan 内容位于该路径，当前没有
  独立的 objective 字段或 Memory 替代对象。

## Requirements

### R1. Compaction request contract

- 新增不可变 `CompactionRequest`，包含 `history`（待压缩旧历史）、`recent_context`
  （保护窗口内的近期背景，不压缩）和 `objective`（当前目标文本或明确的空标记）。
- `ContextCompactor.summarize()` 改为接收 `CompactionRequest`；输出仍为摘要文本。
- Request 由 ContextRuntime 在调用 compactor 前组装；不新增另一份 canonical history、
  不引入 Memory/Dream/Learning 状态或独立压缩器。

### R2. Objective source

- 优先使用当前活跃任务或最近用户指令表达的目标。
- Plan Capability active 时，通过现有 `PlanView.is_active/file_path` 读取并合并 Plan
  内容；inactive 或缺失文件不编造内容。
- 无法可靠确定时，objective 使用最近用户消息的目标描述；若仍无法确定，保留显式
  空标记，不填充模型臆测文本。

### R3. Fixed structured output protocol

压缩 prompt 必须要求且按以下固定顺序包含全部 sections：

`# Objective`、`# Constraints`、`# Decisions`、`# Repository State`、`# Findings`、
`# Failed Attempts`、`# Completed Work`、`# Remaining Work`、`# Verification`。

`Findings` 与 `Verification` 的条目必须附 Coding Evidence，至少支持
`file path::symbol`、测试命令及结果、commit hash、error 单行摘要等证据形式。

### R4. Single prompt ownership

- compaction prompt 模板作为 compaction 模块内的单一常量或资源落位。
- 模板和固定 sections 通过单元测试绑定；不得在多个模块散落同一协议文本。
- 如实现输出校验，非法输出必须被拒绝或按明确降级路径处理；不改变现有 provider
  错误和取消语义。

### R5. Preserved behavior

- 保持 `ContextPolicy` 的五个阈值和既有保护窗口实现不变。
- 85% 自动触发、manual/overflow 触发路径、`CompactionEntry` 写入和 append-only
  replay 行为不变。
- 压缩前后 canonical history 逐条保持一致；旧 Tool Result 仍仅是 Provider
  projection 截断，不能污染 durable history。
- 不修改 Kernel、AgentHarness、Provider/Session/其他 Runtime 的职责边界，不新增
  `CompressionStrategy`、多套压缩器或 per-tool LLM compression。

## Acceptance Criteria

- [x] `CompactionRequest` 契约测试覆盖 history、recent_context、objective 的组装及
      objective/Plan/空标记降级行为。
- [x] Provider prompt 测试断言全部九个 sections、固定顺序和 Findings/Verification
      evidence 要求；若有输出校验，覆盖非法输出的拒绝或降级。
- [x] 85% threshold、manual/overflow、CompactionEntry 写入和 append-only replay 回归
      通过；canonical history 在压缩前后逐条一致。
- [x] 最近 3 个 tool results 与每文件最后一次 `read_file` 的保护窗口回归通过。
- [x] compileall、ruff、mypy、import-linter 和 coverage 门禁通过，或明确记录与本 PR
      无关的既有基线噪声。
- [x] 所有改动局限于 compaction 契约/模板、必要的 request 组装接线、测试和对应
      规划/规范文件；不引入兼容别名或 fallback 压缩架构。

## Key decisions

- 用户已批准“最小只读接线”：`AgentRuntime` 只把当前用户目标和既有保护窗口传给
  `ContextRuntime`，不新增状态、不改变职责、阈值、边界或持久化策略；`CompactionRequest`
  仍由 ContextRuntime 在调用 compactor 前创建。
- `ContextRuntime` 通过 Composition 注入只读 PlanView 结构视图；Plan 内容读取和目标
  合并只用于本次 request，不形成 Capability/Memory 状态镜像。
- 不实现输出校验器；固定协议由单一 prompt template 强制要求，避免把 provider 的
  摘要失败变成新的持久化/恢复分支。Provider error、取消和空摘要错误保持现有契约。
- 实现阶段不使用 subagent；check 阶段允许使用 Trellis check subagent。规划和代码
  验证仍由当前会话协调。

## Out of scope

- 不修改 ContextPolicy 阈值、ContextManager 裁剪顺序或保护窗口算法。
- 不改变 AgentHarness、SessionRuntime、CompactionEntry、SessionState replay 或
  canonical history 的数据模型与所有权。
- 不引入 CompressionStrategy enum、并行压缩器、per-tool LLM compression、Memory
  / Dream / Learning 对象、兼容别名或 fallback 实现。
