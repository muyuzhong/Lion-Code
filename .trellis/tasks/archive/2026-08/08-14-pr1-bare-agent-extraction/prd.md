# PR1 Bare Agent Extraction：核心生命周期移除 Memory 认知

## Goal

让 Agent 的核心 Turn / Session lifecycle 在**完全不存在 Memory 对象**时成立。删除 `AgentRuntimeCoordinator` 与 `SessionLifecycle` 对 Memory 这一具体 Feature 的认知（import、`MemoryTurnHost`/`MemoryTurnPort` 桥、memory 构造参数、turn/abort/clear/restore/close 中的 memory 编排）。保留 generic extension hooks（Capability SPI 的 `before_turn`/`after_turn`）。**ProviderManager → Memory 属 PR2，不在本 PR。**

## 背景与现状核实（2026-08-14，基于真实代码）

- 基座：PR0 已合并进 master（`pr0/four-layer-architecture` 7 提交 fast-forward）。本任务分支 `pr1/bare-agent-extraction` 从 master 派生。
- `AgentRuntimeCoordinator`（`lion_code/agent_runtime.py:302`）：
  - 构造需 `memory: MemoryTurnHost`（line 318, 334），存 `self._memory`。
  - `MemoryTurnHost` Protocol（line 277-299）：`_memory_coordinator`、`_turn_memory_overlays`、`_last_memory_injection`、`_memory_injector`、`_prepare_turn_memory_snapshot`、`_build_turn_memory_overlays`、`_update_session_memory_after_turn`、`_reload_project_memory`、`_reload_session_memory`。
  - `prepare_core_context`（line 456-469）：memory inject（`_memory._memory_injector.inject` + `_last_memory_injection`）。
  - `chat()`（line 759-806）：`memory._prepare_turn_memory_snapshot`、`_update_session_memory_after_turn`、`_build_turn_memory_overlays`。
  - `abort()`（line 750-757）：`self._memory._memory_coordinator.cancel_pending()`。
- `SessionLifecycle`（`lion_code/session_lifecycle.py`）：import `MemoryInjectionReport`/`MemoryTurnHost`；`new_session`/`restore` 中 memory reset/reload（line 62-115）；`close` 中 `_memory_coordinator.close()`（line 133）。
- `MemoryTurnPort`（`lion_code/composition/ports.py:235`）：coordinator↔memory 桥。
- Composition root（`lion_code/composition/agent_builder.py`）：`_build_tooling_graph` 创建 `memory_port`（line 668）；`_build_runtime_coordinator` 传 `memory=memory_port`（line 706）；`_build_session_graph` 构造 `SessionMemoryCoordinator` 并 `memory_port.bind(...)`（line 795）。
- **已存在 generic hooks**：coordinator 的 `chat()` 已有 `await self._capabilities.before_turn()` / `after_turn()`（CapabilityLifecycle）。
- 受影响测试：`tests/integration/test_agent_core_runtime.py` 构造 `SessionMemoryRepository`（line 169-178）并传给 `AgentDependencies`；`tests/memory_runtime/test_core_integration.py` 驱动真实 Agent 断言 memory overlay 到达 provider projection。

## Requirements

### R1. AgentRuntimeCoordinator 无 Memory

- 删除 Memory import（`from lion_code.memory_runtime import ...`）。
- 删除 `MemoryTurnHost` Protocol 与 `memory` 构造参数、`self._memory`。
- `prepare_core_context` 不再做 memory inject（只保留 context projection）。
- `chat()` 删除 `_prepare_turn_memory_snapshot` / `_update_session_memory_after_turn` / `_build_turn_memory_overlays` 编排。
- `abort()` 删除 `_memory_coordinator.cancel_pending()`。
- 保留 generic `capabilities.before_turn()` / `after_turn()`。

### R2. SessionLifecycle 无 Memory

- 删除 `MemoryInjectionReport` / `MemoryTurnHost` import。
- `new_session` / `restore` 删除 memory reset/reload 调用。
- `close` 删除 memory close 调用。

### R3. 删除 Memory↔Core 桥

- 删除 `MemoryTurnHost`（agent_runtime.py）与 `MemoryTurnPort`（composition/ports.py）及其导出。
- Composition root：`_build_tooling_graph` 不再创建 `memory_port`；`_build_runtime_coordinator` 不再接收/传 `memory`；`_build_session_graph` 删除 `memory_port.bind(...)`。

### R4. 保留 generic extension hooks

- Kernel 只调用 generic extension lifecycle（`before_turn`/`after_turn`），不感知其中是否有 Memory participant。
- 本 PR 不把 Memory 重新挂回 Kernel（不 re-home）。

### R5. 极重要约束

不新增：NullMemory、NoopMemory、Memory2、ContextProjectionPort、MemoryContextPort、新 Deferred Memory 类型、ServiceLocator。Memory 功能在 Bare 路径暂时消失是允许的；Full Product 失去部分 Memory 自动行为视为迁移阶段问题。

### R6. ProviderManager → Memory 不做（PR2）

不动 `provider_manager` 的 `memory_query_sink` / `DeferredMemoryQuerySink` 接线。

## Acceptance Criteria

- [ ] 1. `AgentRuntimeCoordinator` 无 Memory import/reference。
- [ ] 2. `AgentRuntimeCoordinator` 构造不需要任何 Memory 参数。
- [ ] 3. `SessionLifecycle` 无 Memory import/reference。
- [ ] 4. `abort` / `clear` / `restore` / `close` 在完全没有 Memory 实例时正常。
- [ ] 5. Core Provider/tool/session/compaction/cancellation 测试不创建 `SessionMemoryRepository`。
- [ ] 6. Core 测试不需要 Memory mock。
- [ ] 7. 不出现 NullMemory 或新的 Feature-specific bridge。
- [ ] 8. 现有 Full Product Memory 测试如果失败，明确标记为后续 Capability re-home 问题（skip/xfail + 说明），而不是重新把 Memory 接回 Kernel。

## 完成后报告

- 所有被删除的 Memory → Kernel 链。
- 明确剩余 Memory 泄漏点（如 `Agent` facade 的 `_session_memory_coord` 委托、`AgentDependencies.session_memory_repository`、`provider_manager` 的 memory_query_sink——后者属 PR2）。

## Notes

- 参考 `tests/OWNERSHIP.md`：Memory 相关测试属 capability；本次把 coordinator-coupled 的 memory 行为测试标记为 re-home。
- 复杂任务：需 design.md + implement.md 后才可 start。
