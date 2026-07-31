# 项目级 Session Memory 实施计划

## 执行前门槛

- 用户已批准并执行 task.py start，当前 task.json.status 为 in_progress。后续只能按本文的切片顺序推进。
- 开始实现前重新阅读 prd.md、design.md、相关运行时规格和当前 git 状态；若当前实现已变化，先修正设计而不是套用本计划。
- 每个切片结束后只暂存本切片写入的文件，运行对应验证、git diff --check，并以中文提交。不得使用 git add -A 或纳入无关工作区改动。
- 在功能真正通过测试前，不得把 planned、设计或候选表述为 implemented。

## Slice 1：项目身份、项目指令与优先 Overlay

### 目标

消除 cwd-hash 的子目录分裂，读取 AGENTS.md 和 CLAUDE.md 并建立 required project Overlay。保持 Auto Memory 的已有文件结构、索引和语义召回能力。

### 预期文件

- lion_code/project_identity.py
- lion_code/memory.py
- lion_code/prompt.py
- lion_code/memory_runtime/types.py
- lion_code/memory_runtime/injector.py
- lion_code/agent.py
- tests/test_project_identity.py
- tests/test_prompt.py
- tests/memory_runtime/test_injector.py
- tests/memory_runtime/test_core_integration.py

### 检查点

1. 临时 Git 根与子目录计算相同 key；非 Git cwd 的规范化结果稳定；两个临时 Git 根各自独立。
2. 根到子目录的 CLAUDE.md、AGENTS.md 顺序为根 CLAUDE、根 AGENTS、子 CLAUDE、子 AGENTS，根外文件不被读入。
3. project、session、auto 混合时，project 与 session 即使 auto 超预算也存在且顺序正确。
4. Provider 收到 Overlay，但 Harness messages、SessionRecorder 和 JSONL 均不包含注入标记。

### 验证

python -m pytest -q tests/test_project_identity.py tests/test_prompt.py tests/memory_runtime/test_injector.py tests/memory_runtime/test_core_integration.py

python -m compileall -q lion_code tests

git diff --check

### 提交

feat: 统一项目身份与项目记忆覆盖层

## Slice 2：Session Memory 模型、持久化与生命周期

### 目标

新增轻量项目或 worktree 级 session-memory.json，接入 Agent 初始化、/clear 和 JSONL restore，但不修改 SessionRepository/SessionRecorder 的职责或 JSONL schema。

### 预期文件

- lion_code/session_memory.py
- lion_code/agent.py
- lion_code/session_runtime 仅在公开导出确有必要时修改
- tests/test_session_memory.py
- tests/memory_runtime/test_lifecycle.py
- tests/memory_runtime/test_core_integration.py
- tests/session_runtime/test_repository.py，仅增加边界回归

### 检查点

1. 同一 ProjectIdentity 的新 repository 实例能恢复所有指定字段；不同 identity 隔离。
2. 损坏 JSON 不被空状态覆盖，调用方可见明确错误。
3. /clear 后 Session Memory 不变而 JSONL session id 改变。
4. restore 旧 JSONL 后加载当前项目的 Session Memory，不把 Session JSONL 内容复制进短期状态。

### 验证

python -m pytest -q tests/test_session_memory.py tests/session_runtime/test_repository.py tests/memory_runtime/test_lifecycle.py tests/memory_runtime/test_core_integration.py

python -m compileall -q lion_code tests

git diff --check

### 提交

feat: 增加项目级会话短期记忆

## Slice 3：固定快照与确定性工具证据

### 目标

把 chat 的顺序改为压缩后固定 Snapshot，避免工具循环中的动态注入；在 finally 中从 canonical 工具消息提取事实，再由受限语义 patch 补足任务状态。

### 预期文件

- lion_code/agent.py
- lion_code/session_memory.py
- lion_code/memory_runtime/coordinator.py，仅在快照 API 需要时
- tests/memory_runtime/test_core_integration.py
- tests/test_session_memory.py
- tests/test_agent_run.py

### 检查点

1. 含工具调用的单轮中，第一次和第二次 Provider 调用的 Overlay 文本完全一致。
2. 当前轮完成的 Auto Memory 预取只在下一用户轮可见。
3. 成功 write_file/edit_file 的 file_path、read_file 路径、测试命令成功或失败、工具错误均由 canonical 工具证据提取。
4. 模型 JSON patch 解析失败或 side query 失败时，确定性字段仍保存，且不会中断主轮。

### 验证

python -m pytest -q tests/memory_runtime/test_core_integration.py tests/memory_runtime/test_coordinator.py tests/memory_runtime/test_lifecycle.py tests/test_session_memory.py tests/test_agent_run.py

python -m compileall -q lion_code tests

git diff --check

### 提交

feat: 固定会话记忆快照并记录工具证据

## Slice 4：任务、handoff、Dream 候选与最小命令

### 目标

提供最小的 /task、/session-memory、/handoff 和 /dream 入口，确保 task 完成只产生受限长期候选，不将短期进度写成 Auto Memory。

### 预期文件

- lion_code/session_memory.py
- lion_code/dream.py
- lion_code/memory.py
- lion_code/application/commands.py
- lion_code/application/session.py
- lion_code/tui/app.py
- lion_code/__main__.py
- tests/test_session_memory.py
- tests/test_dream.py
- tests/application/test_coding_session.py
- tests/tui/test_tui_app.py

### 检查点

1. /task 能查看、切换和结束 active task；结束后清空当前指针并保留完成摘要。
2. /session-memory 只展示项目短期状态；/handoff 保存可继续的交接文本。
3. /dream 获得候选证据，但候选过滤拒绝当前进度、待办、临时测试失败、文件列表和下一步。
4. Dream 写入仍只允许 Auto Memory 目录，无法写 AGENTS.md。
5. REPL 与 TUI 都能分发相同的命令意图。

### 验证

python -m pytest -q tests/test_session_memory.py tests/test_dream.py tests/application/test_coding_session.py tests/tui/test_tui_app.py

python -m compileall -q lion_code tests

git diff --check

### 提交

feat: 提供会话记忆任务与交接命令

## Slice 5：规格收敛与全量验收

### 目标

只在上述功能实际实现并通过验证后，把新的运行时不变量写入 Trellis 规格，并做全量回归。

### 预期文件

- .trellis/spec/backend/runtime-boundaries.md
- 必要时 README.md 的命令说明
- 仅在前述切片暴露缺口时新增测试

### 验证

python -m pytest -q

python -m compileall -q lion_code tests

python -m ruff check lion_code tests

git diff --check

python ./.trellis/scripts/task.py validate 07-30-project-session-memory

### 提交

docs: 补充项目级会话记忆运行时约定

## 完成和归档

所有切片提交后，重新加载实际规格并进行全范围审查。只有全量验收、规格更新和用户确认的功能范围都满足时，才可执行 task.py finish 或 archive；规划完成本身不等于功能完成。
