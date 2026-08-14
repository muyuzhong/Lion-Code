# PR0 架构门禁 — Design

## 1. 目标

在现有 `tests/architecture/_boundaries.py` + import-linter 基础上，把四层边界变成可执行契约。

## 2. 现有门禁结构（已核实）

- `_boundaries.py`：`BOUNDARIES` 元组，每个 `Boundary` = {contract_name, source_package, allowed|forbidden, allow_indirect, external}。`forbidden_roots`/`allowed_roots` 从 `ALL_ROOTS`（lion_code 顶层模块自动发现）推导。
- AST 测试解析生产源码的 import，断言满足 allowed/forbidden。
- import-linter（pyproject.toml `[tool.import-linter]`）用 `import_linter_forbidden_modules` 派生 forbidden_modules，与 `_boundaries.py` 一致。
- `test_import_linter_config_matches_boundaries` 校验两者不漂移。
- 额外 AST 模式扫描在 `test_runtime_boundaries.py`（如 Provider 私有 history、全局 sink、SessionRecorder 构造点等）。

## 3. 设计决策

### 3.1 四层契约 = 新增/改写 `BOUNDARIES`

把旧词汇映射为四层，新增契约：

1. **Kernel 不依赖上层**（改写现有 "Core 不依赖上层运行时包"）：
   - `source_package="lion_code.core"`，`forbidden` 扩为 {providers, tooling, application, observers, tui, session_runtime, permission_state, plan_runtime, skill_runtime, subagent_runtime, memory_runtime, capabilities, autonomy_runtime, dream, dream_adapter, learning_runtime, agent, agent_runtime, usage}。
   - 需 boundary-audit 确认 `core/` 现状无违规（若有，audit 修正后本 child 锁定）。
2. **Harness 只依赖 Kernel**（新增，如可行）：
   - 对 Harness 归属模块（如 `session_runtime`、`provider_manager`、`tooling`）声明 `forbidden={capabilities, autonomy_runtime, dream, learning_runtime, agent}`（agent 门面反向依赖须人工确认——实际 agent 是 Facade，Harness 不应 import agent）。
3. **Capability 不依赖 Agent 引擎**（已有）：保留；扩展 `forbidden` 加 Supervisor 模块。
4. **Supervisor 不依赖 Agent 私有对象**（新增）：
   - `source_package="lion_code"` 的 Supervisor 模块，AST 断言不访问 `agent.Agent._xxx` 私有符号；事件订阅只经 `core.events`/`core.provider_events`（与 event-stream child 的契约测试共用）。

### 3.2 "不是 Kernel" AST 门禁（新测试文件）

新增 `tests/architecture/test_kernel_isolation.py`：AST 扫描 `lion_code/core/`（以及 audit 确定的 Kernel 模块），断言不存在：
- import `memory_runtime`/`plan_runtime`/`capabilities`/`subagent_runtime`/`autonomy_runtime`/`dream`/`learning_runtime`/`mcp_client`；
- 符号 `<relevant-memory>`、`PlanRuntime`、`McpCapability`、`SubagentFactory`、`MemoryContextInjector` 的属性访问/引用。

### 3.3 zero-extension 合法门禁

`test_kernel_isolation.py` 或 `test_composition_root.py` 扩展：构造一个零工具/零能力的 Agent（空 ToolRegistry、无 capability spec），断言装配与一次对话合法（或至少装配合法），验证"zero-extension 合法状态"原则。

### 3.4 Supervisor 订阅契约（与 event-stream 共享）

AST 断言 Supervisor 模块的 import 白名单只含 `core.events`/`core.provider_events` 的事件类型，不含 `agent`/`agent_runtime` 私有符号。event-stream child 的订阅测试是正向样例，本 child 提供反向 AST 扫描（不触碰私有对象）。

### 3.5 一致性维护

修改 `BOUNDARIES` 后：更新 pyproject import-linter、运行 `test_import_linter_config_matches_boundaries`、更新 spec `runtime-boundaries.md` §6 Executable Enforcement。三处同步，避免门禁成为纸面。

## 4. 顺序依赖

- 依赖 08-14-pr0-boundary-audit 的归属结论。audit 完成后本 child 锁定契约与门禁。
- event-stream child 的 Supervisor 订阅契约测试可被本 child 复用为正向样例。

## 5. 验收验证命令

- `lint-imports --no-cache`
- `python -m pytest tests/architecture -q`
- `python -m pytest tests/integration/test_agent_core_runtime.py -q`（zero-extension 装配不破坏现有）
- 全量 `python -m pytest -q`
