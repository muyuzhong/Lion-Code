# 清理 Agent 与 Coordinator 兼容层

## Goal

删除 `Agent` 中为 `Agent.__new__` 窄测试和动态 patch 保留的 `_legacy_*` fallback 路径和
无调用方的委托方法，使 `Agent` 的 Core-scoped 属性和方法成为到 `AgentRuntimeCoordinator`
的单层委托，不再存在第二套状态路径。

## Confirmed Facts

- `agent.py` 有 11 个 `_legacy_*` 属性槽（getter+setter 对），仅在 `_runtime_coordinator`
  为 None 时被读取；正常实例（经 `__init__` 构造）永远走 coordinator 分支。
- `agent.py:604–677` 有 14 个 `_*_core_*` / `_*_background_*` 私有委托方法，其中 12 个
  无任何调用方（agent.py 内部、其他模块、测试均不调用）。
- 3 个委托方法有外部调用方，必须保留：`_schedule_background_operation`
  （agent_lifecycle.py ×5）、`compact_core_context_for_overflow`（application/session.py）、
  `set_terminal_output`（application/session.py）。
- 2 个委托方法被测试直接引用：`_sync_core_usage`（test_usage_observer.py ×2）、
  `_ensure_core_session_ready`（test_mcp_adapter.py patch ×1）。
- coordinator 在 `chat()`(743)、`clear_history()`(897)、`restore_core_session()`(939) 中
  通过 `host._ensure_core_session_ready()` 回调 Agent，形成 coordinator->host->coordinator
  循环委托；此路径仅为允许测试 patch `agent._ensure_core_session_ready` 而存在。
- `abort()`(588–600) 和 `_refresh_memory_context_after_dream()`(937–944) 各有
  `coordinator is None` fallback 分支，同样仅服务 `Agent.__new__` 测试。
- 5 个测试使用 `Agent.__new__` 绕过 `__init__`，是所有 legacy fallback 的唯一消费者：
  - tests/memory_runtime/test_lifecycle.py:106 - 测试 abort 取消 memory + core_runtime
  - tests/runtime/test_usage_observer.py:105 - 测试 _sync_core_usage 投影 observer
  - tests/test_learning.py:61 - 测试 learn_from_current_session 读取 messages
  - tests/test_session_memory_coordinator.py:71 - 测试 dream() 委托
  - tests/test_dream.py:406 - 测试 _refresh_memory_context_after_dream
- `load_legacy_session` / `list_legacy_sessions` / `_migrate_legacy_core_session` 是
  JSONL 格式迁移，不是兼容槽，不在本任务范围内。
- 架构测试 `test_runtime_boundaries.py` 的 `LEGACY_MESSAGE_SYMBOLS` 检查的是
  `_anthropic_messages` / `_openai_messages`，与 `_legacy_*` 槽无关，无需修改。

## Requirements

- R1：删除 12 个无调用方的私有委托方法及其注释：`_prepare_core_context`、
  `_capture_core_text`、`_last_core_assistant`、`_sync_core_outcome`、
  `_before_core_tool_calls`、`_reset_session_counters`、`_reset_core_observers`、
  `_resolve_core_model_limits`、`_context_runtime_state`、
  `_compact_core_context_if_needed`、`_apply_pending_core_context_reset`、
  `_flush_background_operations`。
- R2：删除 11 个属性中的 `_legacy_*` fallback 分支，使每个属性成为单行委托：
  `_core_runtime`、`_session_recorder`、`_context_compactor`、`_context_manager`、
  `_resolved_model_limits_for`、`_core_compaction_required`、`_usage_observer`、
  `_terminal_renderer`、`_memory_coordinator`、`_session_memory`。删除
  `_legacy_last_synced_core_response_count` 及其在 `_sync_core_usage` 中的 fallback。
- R3：删除 `abort()` 中 `coordinator is None` fallback 分支（588–600），使 `abort()`
  始终委托 coordinator。
- R4：删除 `_refresh_memory_context_after_dream()` 中 `coordinator is None` fallback
  分支（940–944），使该方法始终委托 `SessionMemoryCoordinator`。
- R5：将 coordinator 中 3 处 `host._ensure_core_session_ready()` 改为
  `self.ensure_core_session_ready()`，消除循环委托；保留 Agent 上
  `_ensure_core_session_ready` 作为测试 patch 锚点的薄委托。
- R6：保留 `_sync_core_usage` 作为薄委托（仅 `self._runtime_coordinator.sync_core_usage()`），
  保留 `_ensure_core_session_ready` 作为薄委托；两者不再有 fallback 分支。
- R7：保留 `_schedule_background_operation`、`compact_core_context_for_overflow`、
  `set_terminal_output` 不变（有外部调用方）。
- R8：迁移 5 个 `Agent.__new__` 测试为经 `__init__` 构造的 fixture 或直接测试
  coordinator/子运行时；不新增 `__new__` 兼容路径。
- R9：不修改 `load_legacy_session` / `list_legacy_sessions` /
  `_migrate_legacy_core_session` 及架构测试中的 JSONL 迁移白名单。
- R10：不改变任何对外行为：`chat()`、`run()`、`run_once()`、`clear_history()`、
  `restore_core_session()`、`close()`、`abort()`、MCP 初始化、Memory overlay 时序、
  Session Memory 生命周期保持不变。

## Acceptance Criteria

- [x] AC1：`agent.py` 中不再包含任何 `_legacy_` 标识符（`_migrate_legacy_core_session`
  和 `load_legacy_session` 调用除外）。
- [x] AC2：R1 中 12 个无调用方委托方法已删除；R7 中 3 个有外部调用方的方法保留不变。
- [x] AC3：`abort()` 和 `_refresh_memory_context_after_dream()` 不再有
  `coordinator is None` 分支。
- [x] AC4：coordinator 不再通过 `host._ensure_core_session_ready()` 回调 Agent；
  Agent 上的 `_ensure_core_session_ready` 保留为薄委托。
- [x] AC5：5 个 `Agent.__new__` 测试已迁移为经 `__init__` 构造或直接测试 coordinator；
  `grep -rn "Agent.__new__" tests/` 结果不新增。
- [x] AC6：全量测试、compileall、import-linter、架构测试通过；无新增 ruff/mypy/format
  基线回归。
- [x] AC7：`agent.py` 物理行数显著下降（1461 -> 1322，−139 行）。

## Out of Scope

- 收窄 `AgentRuntimeHost` 协议或拆分 `AgentRuntimeCoordinator`（下一任务）。
- 引入 `AgentDependencies` dataclass 或 `build_*_runtime` 辅助方法。
- 修改 JSONL 迁移路径、Core Harness、Provider 协议、ToolRuntime、Memory 语义或
  CLI/TUI UX。
- 清理历史 ruff/format/mypy 基线。

## Notes

- 完成后更新 memory 中的 quality-baseline 记录，标注 agent.py 新行数。
