# PR1 Bare Agent Extraction — Implement

## 目标

按 design.md 把 Core 生命周期 Memory 认知删除。不改 ProviderManager→Memory（PR2）。

## 步骤

### 阶段 1：Coordinator 去 Memory
- [ ] `agent_runtime.py`：删 Memory import、`MemoryTurnHost` Protocol、`memory` 构造参数、`self._memory`；`prepare_core_context` 只 projection；`abort` 删 memory cancel；`chat` 删 3 处 memory 编排（保留 generic before/after_turn）。

### 阶段 2：SessionLifecycle 去 Memory
- [ ] `session_lifecycle.py`：删 Memory import、new_session/restore 的 memory reset/reload、close 的 memory close。

### 阶段 3：删 Memory↔Core 桥
- [ ] `composition/ports.py`：删 `MemoryTurnPort`。
- [ ] `agent_builder.py`：删 `_build_tooling_graph` 的 `memory_port` 创建、`_build_runtime_coordinator` 的 `memory` 参数/传参、`build_agent_composition` 的 `memory_port` 传递、`_build_session_graph` 的 `memory_port.bind`；`SessionMemoryCoordinator` 保留构造。

### 阶段 4：测试更新 + re-home 标记
- [ ] `tests/integration/test_agent_core_runtime.py`：移除 coordinator-memory 接线（SessionMemoryRepository/`_extract_session_memory_semantics` patch/`session_memory_repository=`），相关 memory 用例标 re-home。
- [ ] 排查 `tests/core|providers|tooling|context|runtime`：确认无 `SessionMemoryRepository` 构造 / Memory mock。
- [ ] 将 turn 驱动 Memory 行为的测试标 `skip`/`xfail` + "PR1 Bare Agent Extraction re-home" 理由（design §3.2 列表）。
- [ ] 更新 `tests/architecture/` 门禁（若引用已删符号 `MemoryTurnPort`/`MemoryTurnHost`）。

### 阶段 5：验证
- [ ] `python -m pytest tests/core tests/providers tests/tooling tests/context tests/architecture -q`
- [ ] `python -m pytest -q`（全量）
- [ ] `ruff check` / `ruff format` / `mypy`（改动文件）
- [ ] `lint-imports --no-cache`
- [ ] 确认无 NullMemory/NoopMemory/新 Feature bridge（grep 断言）。

### 阶段 6：spec + 提交
- [ ] 更新 `.trellis/spec/backend/four-layer-ownership.md` / `runtime-boundaries.md`：记录 Memory 从 Core 生命周期移除、`<relevant-memory>` 自动行为 re-home 状态。
- [ ] 提交（commit without asking，branch off master first 已满足——分支 `pr1/bare-agent-extraction`）。

## 评审门

- 验收 1-8（prd.md）逐条满足。
- Core 生命周期无 Memory import（grep `agent_runtime.py|session_lifecycle.py` 无 `memory_runtime`/`session_memory`/`MemoryTurn`）。
- 无 NullMemory/Feature-specific bridge。
- 全量测试：re-home 标记后全部通过或明确 skip/xfail。
- ProviderManager→Memory 未动（grep 确认 `provider_manager` 的 memory_query_sink 原样）。
