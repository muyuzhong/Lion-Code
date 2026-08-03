# 三阶段-6：收敛 Agent Runtime 协调

## Goal

将剩余的 Core Runtime 组装、观察器/上下文/会话生命周期和单次运行协调收敛到现有
`lion_code/agent_runtime.py` 中的 `AgentRuntimeCoordinator`，使 `Agent` 成为工具、
Memory、Plan、Autonomy 与公开 API 的薄组合根。

## Confirmed Facts

- `lion_code/agent_runtime.py` 已有 `LionAgentRuntime`，它是 Provider + Core Harness +
  ToolRuntime 的唯一活跃消息路径；不能新建同名模块或第二套 conversation history。
- `Agent` 仍直接持有 Core runtime 组装、observer/session recorder 重建、context
  projection/compaction、background-operation、`chat()`、`run_once()`、`run()`、
  `clear_history()`、`restore_core_session()` 和 `close()` 等跨轮协调。
- `chat()` 在首次根会话发现 MCP 工具后，必须按“ready → compact → 固定 Memory overlay
  → Core prompt/continue → 同步 usage/outcome → 轮后 Session Memory 更新”的顺序执行。
- `clear_history()` 与 `restore_core_session()` 必须保留 JSONL append/replay、计划模式、
  Model/Thinking 恢复、observer 顺序和项目级 Session Memory 生命周期；`close()` 的
  异常嵌套顺序必须确保 Memory、Core Provider、MCP 环境均获得关闭机会。
- 现有测试和应用层会直接使用 `agent._core_runtime`，并 patch
  `lion_code.agent.TerminalRenderer` 或替换 `_ensure_core_session_ready`；迁移需保留这些
  兼容入口或等价可观察行为。

## Requirements

- R1：在现有 `agent_runtime.py` 中新增 `AgentRuntimeCoordinator` 与窄 Host 协议；它拥有
  Core-scoped state、`LionAgentRuntime`、observer/session recorder、context projection/
  compaction、background-operation、运行结果捕获和 Core 会话生命周期。
- R2：`Agent` 保留当前 public API 和必要私有兼容委托，包括 `core_runtime`、
  `_core_runtime`、`_ensure_core_session_ready`、`compact_core_context_for_overflow`、
  `chat()`、`run_once()`、`run()`、`clear_history()`、`restore_core_session()` 与 `close()`。
- R3：MCP 首次发现、Tool routing、SessionMemoryCoordinator、AutonomyRuntime、
  LearningRuntime、AgentLifecycle、Plan prompt 和确认 UI 仍由 `Agent` 所在边界拥有；
  coordinator 只经明确 Host 回调使用它们。
- R4：保持一份 canonical Core history、一份 SessionRecorder 和一个活跃 Provider；
  `AgentRuntimeCoordinator` 不反向导入 `Agent`，也不绕过 `LionAgentRuntime` 或
  `ToolRuntime`。
- R5：保留 `lion_code.agent.TerminalRenderer` 的动态 patch 锚点，并保证终端、结构化
  前端、子 Agent 和关闭顺序的现有行为不变。

## Acceptance Criteria

- [ ] AC1：Core 组装、observer/session-ready、context projection/compaction、运行结果
  捕获、单次运行和 Core 会话生命周期均由 `AgentRuntimeCoordinator` 独立拥有；
  `Agent` 只保留组合根和薄委托。
- [ ] AC2：`chat()` 的 MCP 初始化、Memory overlay 时序、Core prompt/continue、usage/
  budget/outcome 更新和 Session Memory 轮后更新不变，且不会创建第二份消息历史。
- [ ] AC3：`run()` 的 timeout/aborted/model-error 结构化结果、`run_once()` 的文本/token
  捕获、context compaction 和 Plan pending reset 行为保持不变。
- [ ] AC4：clear/restore 保留 JSONL、Model/Thinking、计划模式、observer 顺序和 Session
  Memory 生命周期；`close()` 仍即使前序关闭失败也尝试关闭其余资源。
- [ ] AC5：`lion_code.agent.TerminalRenderer` patch 与 `_core_runtime` /
  `_ensure_core_session_ready` 兼容入口继续可用；新模块不在模块级导入 `Agent`。
- [ ] AC6：相关 runtime/integration/application/memory/tooling 回归、完整测试、
  compileall、导入边界、改动范围静态检查、差异检查与 Trellis validation 通过；台账记录
  实际物理行数和已知基线差异。

## Out of Scope

- 改变 Core Harness、Provider 协议、ToolRuntime 中间件、JSONL schema、Memory 内容语义、
  Plan/Autonomy 产品行为或 CLI/TUI UX。
- 清理与本边界无关的历史 Ruff/format/mypy 基线，或处理并行的质量基线/TUI 文档改动。
- 继续拆分 Tool routing、SessionMemoryCoordinator、AutonomyRuntime、LearningRuntime 或
  AgentLifecycle 的内部职责。

## Planning Status

阻塞问题为空。该任务是三阶段最终且最高耦合的切片，采用“扩展现有
`agent_runtime.py`、单一 Core history、兼容委托”的设计；已完成复杂任务所需设计与
实施计划，等待用户明确批准后才启动并改代码。
