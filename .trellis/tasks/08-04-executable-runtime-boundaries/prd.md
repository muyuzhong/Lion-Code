# 第四阶段：运行时边界可执行约束

## Goal

把 Runtime Boundary 文档中的运行时不变量变成可重复执行的本地与 CI 回归门禁，避免后续重构重新引入第二套消息历史、Session Writer 或全局 TUI 输出通道。

## Confirmed Facts

- .trellis/spec/backend/runtime-boundaries.md 已定义唯一 Canonical Core History、唯一运行时 SessionRecorder、Provider 不持有私有消息历史、TUI 通过 application/core 事件消费输出、Memory Overlay 仅为临时 Provider projection。
- 当前 pyproject.toml 有 3 条 import-linter 合同，lint-imports --no-cache 在 150 个文件、750 条依赖上通过。
- CI 已以阻塞步骤运行 lint-imports --no-cache，因此本任务不需要新增 CI 工作流。
- 当前 core 没有直接导入 providers、tooling、application 或 tui；providers 的绝对产品导入均指向 core；application 不导入 tui。
- 当前 TUI 的运行时交互导入来自 application/core，并保留 config、prompt、version 等展示或配置辅助依赖；它不直接导入 providers、tooling、memory_runtime 或 session_runtime。
- SessionRecorder 的构造点只有两个：AgentRuntimeCoordinator.reset_core_observers 的活跃会话 writer，以及 Agent._migrate_legacy_core_session 的一次性旧 JSON 迁移 writer。后者不是第二个活跃会话路径，必须作为受控例外记录。
- 现有 tests/memory_runtime/test_injector.py 已验证 overlay 投影不修改输入 canonical messages；本任务补充防止绕过该路径的架构扫描。

## Requirements

### R1. Import Dependency Contracts

- R1.1 core 不得直接或间接依赖 providers、tooling、application、tui。
- R1.2 providers 的产品层导入只允许指向 core 抽象或 providers 自身。
- R1.3 application 不得依赖 tui。
- R1.4 tui 不得绕过 application/core 直接依赖运行时引擎层；config、prompt、version 等展示辅助模块作为显式窄例外保留。
- R1.5 产品代码不得反向导入 tests 或 benchmarks。
- R1.6 新合同取代现有过窄的 TUI 直接依赖合同；lint-imports 必须保持零 broken contracts。

### R2. Architecture Regression Tests

- R2.1 新增独立 architecture 测试，采用 Python AST 扫描生产源码而不是脆弱的纯文本匹配。
- R2.2 禁止 Provider 实现持有 messages/history 形式的实例级私有会话历史。
- R2.3 禁止回流已废弃的 _openai_messages、_anthropic_messages 路径；唯一允许位置是只读迁移模块 lion_code/session_runtime/legacy.py。
- R2.4 禁止定义或调用全局 set_sink 输出桥。
- R2.5 将 SessionRecorder 构造点限制为当前两个有文档依据的入口；禁止新的构造点、别名导入或绕过 SessionRecorder 直接使用 JSONL writer。
- R2.6 禁止 memory_runtime 与 session_memory_coordinator 调用 Core Harness 的消息替换、排队或清空 API；Memory Overlay 只能产出临时投影。

### R3. Documentation Alignment

- R3.1 更新 Runtime Boundary 规范，记录每个自动门禁、迁移 writer 例外、运行命令及失败时的修复方向。
- R3.2 更新质量基线文档中 import-linter 的合同清单和数量，使其与 pyproject.toml 一致。

## Acceptance Criteria

- [ ] lint-imports --no-cache 通过，且包含 R1.1-R1.5 的 5 条明确合同。
- [ ] 新 architecture 测试能在受控的临时源码片段或 AST fixture 上证明每一类禁止模式会失败，并在当前源码上通过。
- [ ] Provider、TUI、Memory Overlay、Session Writer 与旧消息路径的当前合法例外都被精确记录；测试不以宽泛 grep 误伤合法迁移或测试 double。
- [ ] 现有 MemoryContextInjector 的输入不可变行为继续通过，canonical Core history 与 JSONL 中不包含 overlay 标记。
- [ ] 修改范围限于 import 合同、架构测试及相关规范/质量文档；不重构 Agent、Provider、TUI 或 Session 实现。
- [ ] 受影响测试、完整 pytest、compileall、lint-imports、git diff --check 与 Trellis 任务校验通过。

## Out of Scope

- 不改变 Provider 协议、Core Harness、JSONL schema、TUI 视觉/交互行为或 Memory 的召回策略。
- 不删除 legacy.py 的只读 JSON 迁移能力，也不把迁移 writer 重构为新的运行时路径。
- 不处理当前工作区中与本任务无关的 docs/tui-migration-audit.md 删除、tests/application/test_coding_session.py 修改及 08-01-quality-baseline 目录。
