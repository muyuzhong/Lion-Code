# 项目级 Session Memory（短期记忆）

## Goal

在不改变 canonical Session messages 与 JSONL 完整会话记录职责的前提下，为每个项目或 Git worktree 持久化轻量工作状态。项目指令、当前 Session Memory 和按问题召回的 Auto Memory 必须统一以 Provider 临时 Overlay 进入模型上下文。

目标主链路为：

会话准备 → 上下文压缩 → 长期记忆预取 → Provider 投影 → 模型执行。

用户已批准执行，任务现处于 in_progress。实现仍须按切片逐项验证；在对应测试通过前不得将规划能力描述为已实现。

## Current Constraints

- SessionRepository 与 SessionRecorder 继续只负责 JSONL 的完整记录、恢复和压缩重放，不能被 Session Memory 替代。
- 现有 Auto Memory 保留文件存储、索引、语义预取和非破坏性 Overlay 注入；它不再承担进行中的工作状态。
- 项目指令均为不可信的项目内容，只能作为 Provider 的 user-role 临时上下文，不能提升为 system 权威，且 AI 不能自动写入 AGENTS.md。
- 第一版只保存当前工作状态，不引入产品侧 PRD、任务树、阶段机、子任务或复杂计划系统。
- /clear 创建新 JSONL 对话但必须保留同项目 Session Memory；恢复旧 JSONL 时也必须重新加载当前项目状态。

## Requirements

### R1. 统一项目身份

- Git 仓库以当前 worktree 的 Git 根目录为项目身份；从子目录启动必须命中同一身份。
- 非 Git 目录以规范化后的 cwd 为项目身份。
- Auto Memory 与 Session Memory 都通过该身份选取存储位置，不能再直接对原始 Path.cwd() 求哈希。

### R2. 只读项目记忆

- 从项目根目录到当前 cwd 逐级读取项目指令。
- 同一目录先加载 CLAUDE.md 兼容来源、再加载 AGENTS.md；更深目录覆盖更浅目录，AGENTS.md 覆盖同目录 CLAUDE.md。
- 项目记忆只读取人写的技术栈、命令、架构约定和禁区；不得由模型自动改写。

### R3. Auto Memory 的职责边界

- 长期 Memory 名称统一为 Auto Memory，类型只允许 user、feedback、project、reference。
- project 仅保存长期有效的项目决策及其原因；ongoing work、goals、deadlines、临时进度、待办和下一步不得写入该类型。
- 保留现有的文件索引、语义选择、异步预取和 Overlay 注入。

### R4. 项目级 Session Memory

- 每个项目或 worktree 具有独立、跨单个 JSONL 会话的持久化状态。
- 最小状态包含：current goal、active task、completed、pending、decisions、blockers、relevant files、verification、previous handoff、next step。
- 状态必须轻量、可读、可恢复，并在损坏时避免静默覆盖用户已有数据。

### R5. 生命周期和每轮快照

- Agent 初始化按 项目身份 → 项目指令 → Session Memory → active task → handoff 的顺序准备状态。
- 每个 chat 轮次先完成上下文压缩，再加载并固定该轮 Session Memory，启动 Auto Memory 异步召回，最后组装 Provider 投影。
- 同一轮中的工具循环不得因异步召回完成而改变已固定的三层 Overlay 快照。
- /clear 保留项目级短期状态；恢复旧 JSONL 仍以当前项目状态为准；新项目实例不得携带旧项目的任一层上下文。

### R6. 每轮更新与长期候选

- 每轮结束使用用户输入、最终回复和 canonical 工具事件更新短期状态。
- 文件变更、测试命令结果和工具错误优先从工具事件确定性提取；模型只补充目标、任务、决策、待办、阻塞、handoff 和下一步等任务语义。
- 完成任务、显式 /dream 或阶段性整理时，只能从 Session Memory 提取长期候选：稳定用户偏好、明确行为反馈、已验证的架构决策及原因、可复用失败经验、外部资源指针。
- 当前进度、未完成待办、临时测试失败、文件修改清单、下一步操作不得沉淀为 Auto Memory。

### R7. 最小交互

- 用户能够查看 active task 和完整 Session Memory。
- 用户能够切换或结束当前 task，手动生成 handoff，并把当前 task 交给 /dream 整理。
- REPL 与 TUI 对同一命令语义保持一致。

## Non-goals

- 不修改 JSONL 的 schema、记录时机或恢复语义。
- 不将项目指令或 Session Memory 写入 canonical Harness messages、SessionRecorder 或 JSONL。
- 不自动迁移、删除或合并用户旧的 cwd-hash Auto Memory 文件；迁移策略不是第一版范围。
- 不增加项目内工作目录切换命令。当前产品以新建 Agent 或会话实例打开另一项目；该入口必须重新绑定全部三层上下文。
- 不自动把候选写入 AGENTS.md，也不把 Session Memory 当作长期知识库。

## Acceptance Criteria

- [x] Git 根目录与其子目录得到相同项目键；非 Git cwd 得到稳定规范化项目键；不同 worktree 不共享状态。
  （`project_identity.py` 用 `git rev-parse --show-toplevel`；`tests/test_project_identity.py` 验证）
- [x] AGENTS.md 与 CLAUDE.md 从项目根到 cwd 逐级加载，且优先级符合 R2。
  （`prompt.py` `load_project_context_files` 逐级加载；`tests/test_prompt.py` 验证）
- [x] 项目记忆、Session Memory、Auto Memory 按 项目记忆 > Session Memory > Auto Memory 的顺序只进入 Provider 投影；canonical 消息和 JSONL 不含注入块。
  （`MemoryContextInjector` 注入三层 Overlay；`tests/memory_runtime/test_injector.py` 验证不可变性）
- [x] /clear 后同一项目的 Session Memory 保留；恢复旧 JSONL 时重新加载当前项目 Session Memory；新项目实例不泄漏旧项目状态。
  （`SessionMemoryCoordinator` 在 clear/restore 中 `_reload_project_memory` + `_reload_session_memory`；集成测试验证）
- [x] 一次含工具调用的 chat 中，两次 Provider 调用看到的 Overlay 快照相同；下一用户轮才允许使用已完成的 Auto Memory 预取。
  （`_prepare_turn_memory_snapshot` 在轮次开始时固定 Overlay；`tests/test_agent_run.py` 验证）
- [x] 工具事件可确定性记录成功的 write_file/edit_file 路径、识别测试命令通过或失败、并保留工具错误作为阻塞证据。
  （`_update_session_memory_after_turn` 从 canonical 工具消息提取确定性证据）
- [x] 任务完成后的候选提取拒绝临时进度、待办、文件列表、临时失败和下一步，只接受 R6 的五类长期内容。
  （`dream.py` prompt 明确拒绝 progress/pending/next steps/file lists/temporary failures；`tests/test_dream.py` 验证）
- [x] /task、/session-memory、/handoff、/dream 的最小命令路径有单元或应用层测试。
  （`application/commands.py` 注册 4 个命令；`tests/application/test_coding_session.py` + `tests/tui/test_tui_app.py` 验证）
- [x] 每个实施切片独立运行目标测试、执行 diff 检查，并以中文提交信息提交；无关工作区改动不被纳入提交。
  （各切片已按此标准提交，全量 577 passed）

## Planning Note

现有 .trellis/spec/backend/runtime-boundaries.md 记录的是当前已实现的运行时事实。由于本任务尚未进入实现，不提前把目标设计写成现状；实现并验证后才在完成阶段更新该规格。
