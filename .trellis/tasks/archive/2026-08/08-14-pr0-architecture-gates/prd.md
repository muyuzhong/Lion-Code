# PR0 架构门禁测试

## Goal

新增可执行架构门禁，使四层边界（Kernel / Harness / Capability / Supervisor）尽可能由**代码验证**而不是只写文档。基于现有 `tests/architecture/_boundaries.py` + import-linter 双通道扩展。

## 现状（已核实）

- 现有门禁：`tests/architecture/_boundaries.py` 定义 `BOUNDARIES`（import 方向，AST 测试 + import-linter 双通道，`test_import_linter_config_matches_boundaries` 强制二者一致）。
- 现有契约用的是旧词汇：Core / Providers / Application / TUI / Capabilities。**没有 Kernel/Harness/Supervisor 四层契约**。
- 现有 gate 测试：test_runtime_boundaries.py、test_application_ports.py、test_tool_routing.py、test_composition_root.py。
- "Core 不依赖上层运行时包"最接近"Kernel 不依赖 Harness"，但 `core` 是否完全干净需 child boundary-audit 核实（如 `core/` 是否 import `usage`/`permission_state`/`plan_runtime` 等）。

## Requirements

### R1. 四层 import 方向门禁

新增/扩展边界契约，使下列方向由代码强制：
- **Kernel 不依赖 Harness/Capability/Supervisor/Application/TUI**：`lion_code.core`（及 Kernel 归属的其他模块）不得 import `providers`、`tooling`、`session_runtime`、`application`、`observers`、`tui`、`plan_runtime`、`skill_runtime`、`subagent_runtime`、`usage`、`autonomy_runtime`、`dream*`、`learning_runtime`、`memory_runtime`、`capabilities`、`agent`、`agent_runtime`。
- **Harness 不依赖 Capability/Supervisor**：Harness 归属模块只依赖 Kernel + 自身。
- **Capability 不依赖 Agent 引擎**（已有）且不依赖 Supervisor。
- **Supervisor 不依赖 Agent 私有对象**：Supervisor 归属模块不得 import `agent` 内部私有符号；订阅事件只能经 `core.events`/`core.provider_events` 公开类型。

### R2. "不是 Kernel" 门禁

断言 Kernel 归属代码不引用 Capability/Supervisor 专属符号：`<relevant-memory>`（`MemoryContextInjector`）、`Plan`（`PlanRuntime`/`PlanState`）、MCP（`mcp_client`/`McpCapability`）、SubAgent（`SubagentFactory`）、Autonomy、Dream、Learning。以 AST 扫描断言 `core/` 不出现这些符号的 import 或属性访问。

### R3. zero-extension 合法门禁

断言 zero-tool / no-capability 装配是合法状态（装配不要求任何 capability 存在）。与 `test_composition_root.py` 的"one-shot builder 无 Agent 运行时构造"配合。

### R4. Event Stream 订阅契约门禁

（与 event-stream child 的 Supervisor 订阅契约测试一致，本 child 可复用或引用）Supervisor 只消费 Kernel 公开事件契约。

### R5. 一致性

任何边界调整必须同步 `_boundaries.py` 与 `pyproject.toml` 的 import-linter 配置（`test_import_linter_config_matches_boundaries` 强制一致），并同步更新 spec `runtime-boundaries.md` 的 "Executable Enforcement" 小节。

## Acceptance Criteria

- [ ] `_boundaries.py`/pyproject 中出现四层契约（Kernel/Harness/Capability/Supervisor），`lint-imports --no-cache` 通过。
- [ ] 新增 "不是 Kernel" AST 门禁测试通过，且当前 `core/` 通过（如不通过，需 boundary-audit 先行修正归属后本 child 再锁定——顺序依赖见父 design §7）。
- [ ] zero-extension 合法门禁测试存在并通过。
- [ ] 现有 gate 测试（test_runtime_boundaries / test_application_ports / test_tool_routing / test_composition_root）全通过。
- [ ] 无 R5 禁止项：不新增 NullMemory/NullPlan/NoopCapability、ServiceLocator/CapabilityContext、build_meta_agent、大规模目录搬迁、Feature-specific protocol。
- [ ] 全量测试通过。

## Notes

- 依赖 child 08-14-pr0-boundary-audit 的归属结论（哪些模块属于 Kernel/Harness/...）。若 audit 尚未完成，本 child 先只写框架，锁定用 audit 结论。
- 参考父 design §5 的门禁策略。
