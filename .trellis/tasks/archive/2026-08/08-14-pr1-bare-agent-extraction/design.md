# PR1 Bare Agent Extraction — Design

## 1. 设计决策

### 1.1 核心原则：Core 生命周期零 Memory 认知

`AgentRuntimeCoordinator` + `SessionLifecycle` 是 Core 生命周期。PR1 删除它们对 Memory 的一切 import/参数/编排。generic Capability hooks（`before_turn`/`after_turn`）保留，作为唯一扩展点。

### 1.2 SessionMemoryCoordinator 的去留

- **Coordinator-coupled 部分删除**：`MemoryTurnPort`/`MemoryTurnHost` 桥、turn snapshot/update/overlay/inject、abort cancel。这些是 Memory 自动行为进入 Core 的通道，全部断开。
- **SessionMemoryCoordinator 类保留在代码库**（不删除 Memory 能力代码），但**不再桥接进 coordinator**。它在 composition root 中仍被构造，用于**独立于 turn 循环**的能力：Session Memory 持久化、`/handoff`/`/task`/`/session-memory` 命令、Dream 协调、项目上下文加载。
- **结果**：Full Product 暂时失去 turn 驱动的 Memory 自动行为（`<relevant-memory>` 召回、turn overlay 注入、turn 后自动抽取）——这正是用户允许的"迁移阶段问题"。相关测试标记 re-home（skip/xfail + 理由）。

### 1.3 目标生命周期（改动后 chat()）

```
await self._capabilities.before_turn()        # generic hook（保留）
→ ensure_core_session_ready()
→ compact_core_context_if_needed()
→ self._runtime.prompt(user_message)          # prepare_core_context 只做 projection
→ while apply_plan_context_reset(): continue_()
→ sync_core_outcome()
→ self._capabilities.after_turn()             # generic hook（保留）
```
删除：`memory._prepare_turn_memory_snapshot`、`memory._update_session_memory_after_turn`、`memory._turn_memory_overlays = memory._build_turn_memory_overlays()`。

## 2. 逐文件改动

### 2.1 `lion_code/agent_runtime.py`

- 删除 `from lion_code.memory_runtime import (MemoryContextInjector, MemoryInjectionReport, MemoryOverlay)`（line 49-52）。
- 删除 `class MemoryTurnHost(Protocol)`（line 277-299）。
- `AgentRuntimeCoordinator.__init__`：删除 `memory: MemoryTurnHost` 参数与 `self._memory = memory`；docstring 去掉 memory 条目。
- `prepare_core_context`：删除 `projected, memory_report = self._memory._memory_injector.inject(...)` 与 `self._memory._last_memory_injection = memory_report`；直接 `return prepared.messages`（或 `tuple(...)`）。
- `abort()`：删除 `self._memory._memory_coordinator.cancel_pending()`。
- `chat()`：删除 3 处 memory 编排（见 §1.3）。
- 若 `agent_runtime.py` 定义了 `MemoryTurnPort` 相关导出/类型引用，一并清理。

### 2.2 `lion_code/session_lifecycle.py`

- 删除 `from lion_code.memory_runtime import MemoryInjectionReport` 与 `MemoryTurnHost` import。
- `new_session()` / `restore_session()`：删除 `memory = self._memory`、`_memory_coordinator.reset()`、`_reload_project_memory()`、`_reload_session_memory()`、`_last_memory_injection = MemoryInjectionReport()`、`_turn_memory_overlays = _build_turn_memory_overlays()`。
- `close()`：删除 `await self._memory._memory_coordinator.close()`。
- 若 `SessionLifecycle` 通过 coordinator 拿 memory（`self._coord._memory`），改为不访问。

### 2.3 `lion_code/composition/ports.py`

- 删除 `class MemoryTurnPort`（line 235）及其关联类型/导出。

### 2.4 `lion_code/composition/agent_builder.py`

- `_build_tooling_graph`：删除 `memory_port = MemoryTurnPort()`（line 668），`_ToolingGraph` 去掉 `memory_port` 字段。
- `_build_runtime_coordinator`：删除 `memory_port: MemoryTurnPort` 参数（line 697）与 `memory=memory_port`（line 706）；签名不再传 memory。
- `build_agent_composition`：删除 `memory_port` 相关传递（line 280-298 附近）。
- `_build_session_graph`：删除 `memory_port: MemoryTurnPort` 参数（line 735）；删除 `memory_port.bind(session_memory_coord, ...)`（line 795）。`SessionMemoryCoordinator` 仍构造（供独立能力用）。
- 删除 `MemoryTurnPort` import。

### 2.5 `lion_code/agent.py`（facade）— 边界处理

- `Agent` 的 `_session_memory_coord`/`_memory_injector`/`_last_memory_injection` 等 facade 委托：若仍由 composition 构造的 `SessionMemoryCoordinator` 提供，则保留（Memory 能力未删）。**但**必须确认这些委托不再被 Core 生命周期调用（它们服务于命令/持久化）。
- 若 facade 委托引用了 coordinator 的 memory 字段，需改为引用 composition 传入的 `SessionMemoryCoordinator` 实例（若 composition 还提供）。

## 3. 测试影响与 re-home 标记策略

### 3.1 需要更新的测试

- `tests/integration/test_agent_core_runtime.py`：删除 `SessionMemoryRepository` 构造与 `_extract_session_memory_semantics` patch、`session_memory_repository=` 传参（若仅服务于 coordinator memory）。若测试断言 turn 后 memory 行为 → 该部分标记 re-home。
- `tests/core/*`、`tests/providers/*`、`tests/tooling/*`、`tests/context/*`：确认无 `SessionMemoryRepository` 构造（验收 #5/#6）。
- `tests/runtime/test_agent_runtime.py`：若构造 coordinator 传 memory → 移除。
- `tests/architecture/test_kernel_isolation.py` / `test_runtime_boundaries.py`：若 AST 门禁引用 `MemoryTurnPort`/`MemoryTurnHost` 或 memory 符号 → 更新门禁（这些符号消失）。

### 3.2 re-home 标记（验收 #8）

以下测试断言 turn 驱动的 Memory 自动行为，PR1 后会失败 → 加 `pytest.mark.skip`/`xfail` + 理由 "PR1 Bare Agent Extraction：Memory 自动行为 re-home 到 Capability 的前置条件；见 spec four-layer-ownership"：

- `tests/memory_runtime/test_core_integration.py`（memory overlay 到 provider projection）
- `tests/memory_runtime/test_lifecycle.py`（coordinator abort 取消 memory）
- `tests/integration/test_agent_core_runtime.py` 中 memory 相关用例
- `tests/test_session_memory_coordinator.py` 中 turn 驱动用例（若受影响）
- 其他因删除 coordinator memory 而失败的 Full Product Memory 测试

标记为 re-home 的测试**不删除、不改成通过**，只标 skip/xfail + 原因，留待 Capability re-home PR。

### 3.3 保留通过的能力测试

- `tests/memory_runtime/test_injector.py`（MemoryContextInjector 纯逻辑）→ 应继续通过。
- `tests/memory_runtime/test_coordinator.py`（MemoryCoordinator 纯逻辑）→ 应继续通过。
- `tests/test_session_memory.py`（SessionMemory 持久化）→ 应继续通过。
- `tests/test_plan_runtime.py`、`test_autonomy*.py`、`test_dream.py` 等非 coordinator-memory 耦合 → 视情况。

## 4. 剩余 Memory 泄漏点（完成后报告）

- `Agent` facade 的 `_session_memory_coord` / `_memory_injector` 等委托（composition 仍构造 SessionMemoryCoordinator）。
- `AgentDependencies.session_memory_repository` 字段。
- `provider_manager` 的 `memory_query_sink` / `DeferredMemoryQuerySink`（**属 PR2，本 PR 不动**）。
- `capabilities/`、`memory_runtime/`、`session_memory*.py`、`dream*.py` 中保留的 Memory 能力代码。
- `application/`、`tui/` 中对 session-memory 命令的 dispatch（仍可用，因 SessionMemoryCoordinator 保留）。

## 5. 验证命令

- `python -m pytest tests/core tests/providers tests/tooling tests/context -q`（Core 无 memory 依赖）
- `python -m pytest tests/architecture -q`（门禁更新后通过）
- `python -m pytest -q`（全量：re-home 标记后通过/跳过）
- `ruff check` / `ruff format` / `mypy`（改动文件）
- `lint-imports --no-cache`（import 契约不破坏）
