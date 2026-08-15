# Test Ownership Map — 全量测试审计结果（108 文件）

> 由 2026-08-14 全量测试审计产出。这是 `tests/OWNERSHIP.md` 的来源数据。
> 分类枚举：kernel / harness / capability / supervisor / product / eval / mixed。

## 目录级归属

| 目录 | Layer | 说明 |
|---|---|---|
| tests/architecture/ | （门禁元测试） | 边界强制 AST/行为测试，非层测试。`_boundaries.py` 是辅助模块 |
| tests/core/ | **kernel（纯）** | AgentHarness 循环、取消、provider events。名字准确 |
| tests/context/ | **kernel** | Context Window / Compaction / projection / policy |
| tests/providers/ | **kernel** | Provider Port 实现（Anthropic/OpenAI/fake/stream/limits/thinking/oneshot/factory） |
| tests/runtime/ | **harness（名字误导）** | `lion_code/agent_runtime.py`(coordinator) + observers(TerminalRenderer/UsageObserver)。不是 Kernel |
| tests/session_runtime/ | **harness** | SessionRecorder / SessionRepository / JSONL 持久化 |
| tests/adapters/ | **harness** | Tool 协议适配（adapt_lion_tool/to_core_result/adapt_active_tools） |
| tests/tooling/ | **harness（大部）+ capability/supervisor 触碰** | ToolRegistry/ToolRuntime/Middleware/Permission/execution policy；含 skill/subagent/mcp/plan-tools |
| tests/application/ | **harness（大部）+ 少量 supervisor/skill** | 应用 facade/ports/provider settings |
| tests/memory_runtime/ | **capability** | Memory（coordinator/injector/lifecycle/core_integration） |
| tests/capabilities/ | **capability** | Capability SPI（registry/runtime/migration） |
| tests/benchmarks/ | **eval（层外）** | 评测/基准基础设施 |
| tests/tui/ | **harness（大部）+ product（test_tui_app）** | TUI 组件 + 完整应用集成 |

## 文件级归属（重点文件）

### tests/core/（kernel 纯）
- fakes.py（fixture）、test_harness.py、test_dynamic_configuration.py、test_cancellation.py — 全 kernel。

### tests/integration/（跨层）
- test_agent_core_runtime.py — **mixed（kernel+harness+capability）**：真实 Agent 全装配；Kernel(loop/compaction/usage/budget/cancellation/tool-call) + Harness(ToolRegistry/ToolRuntime/SessionRepository/SessionRecorder/ProviderManager) + Capability(Plan 工具/sub-agent)。名字带 "core runtime" 但非纯 Kernel。
- test_application_coding_session.py — **mixed（kernel+harness+supervisor）**：LionCodingSession；含 overflow auto-retry/recovery 编排 = Supervisor。
- test_core_tool_runtime.py — **mixed（kernel+harness）**：AgentHarness→ToolRuntime→LionTool。
- test_provider_core_tool_runtime.py — **mixed（kernel+harness）**：真实 OpenAICompatibleProvider + httpx.MockTransport。

### tests/runtime/（harness）
- test_agent_runtime.py — **mixed（harness+kernel）**：coordinator + observers + ToolRuntime。
- test_terminal_renderer.py — harness（event/trace sink）。
- test_usage_observer.py — harness（observer 喂 Kernel usage）。

### tests/session_runtime/（harness）
- test_legacy_fallback.py、test_recorder.py、test_repository.py — 全 harness 持久化。

### tests/tooling/（harness 为主，mixed 文件列全）
- test_registry.py、test_runtime.py、test_hook_middleware.py、test_permission_middleware.py、test_permission_policy.py、test_concurrency_policy.py、test_result_policy.py、test_read_freshness.py、test_tool_search.py、test_builtin_tools.py、test_temporary_tools.py — **harness**。
- test_agent_runtime.py — **mixed（harness+capability[Plan]）**：Agent._execute_tool_call + plan-mode toggle。
- test_agent_internal_runtime.py — **mixed（harness+capability[SubAgent]+supervisor[schedule_wakeup]）**。
- test_capability_runtimes.py — **capability**（SkillRuntime/SubagentExecutor）。
- test_tool_environment.py — **mixed（harness+capability[MCP]）**。
- test_tool_selection.py — **mixed（harness+capability[SubAgent]）**。
- test_mcp_adapter.py — **mixed（capability[MCP]+harness）**。
- test_internal_tools.py — **mixed（harness+capability[Skill/Plan/SubAgent]+supervisor[wakeup]）**。
- test_skill_registry_view.py — **mixed（capability[Skill/SubAgent]+harness）**。

### tests/memory_runtime/（capability）
- test_coordinator.py、test_injector.py — **capability**（Memory）。
- test_core_integration.py — **mixed（capability[Memory]+kernel）**：Memory overlays 到 provider projection，驱动真实 Agent.chat。
- test_lifecycle.py — **capability（Memory）** + 一个 harness case（coordinator abort）。

### tests/capabilities/（capability）
- test_capability_registry.py、test_capability_migration.py、test_capability_runtime.py — **capability**（SPI / MCP/Skill/SubAgent migration，部分构造真实 Agent）。

### tests/application/（harness facade + supervisor/skill）
- fakes.py（fixture）。
- test_coding_session_ports.py — **mixed（harness+supervisor）**：应用 facade + overflow retry 编排。
- test_provider_settings.py — harness。
- test_skill_commands.py — capability（Skill）。

### tests/tui/（harness UI + product）
- test_tui_adapter.py — harness（事件→UI）。
- test_tui_app.py — **product integration**（完整 Textual 应用 + 真实 Agent）。
- test_tui_autocomplete.py / test_tui_config.py / test_tui_file_drop.py / test_tui_themes.py — harness（TUI 组件）。

### tests/ 顶层（跨层）
- test_agent_run.py — **kernel（为主）**：Agent.run() 契约；接线 SessionRepository 但断言 Kernel 不变量。
- test_autonomy.py / test_autonomy_flow.py / test_autonomy_goal_loop.py — **supervisor**（Autonomy/Goal lifecycle）。
- test_cli.py — **product**（CLI/REPL 驱动 Agent + session memory）。
- test_dream.py — **supervisor**（Dream）+ Memory 触碰。
- test_hooks.py — **harness**（permission/safety/hooks/execution backend）。
- test_learning.py — **supervisor**（Learning）。
- test_mcp_client.py — **capability**（MCP）。
- test_model_query.py — **kernel**（Provider 端口薄包装）。
- test_plan_runtime.py — **capability**（Plan，含 Plan reset）。
- test_project_identity.py — harness（identity/config）。
- test_prompt.py — harness（prompt composition）。
- test_provider_manager.py — harness（ProviderManager）。
- test_session_memory.py / test_session_memory_coordinator.py — **capability**（Memory）。
- test_usage.py — **kernel**（Usage/Budget 语义）。
- test_ui.py — harness（REPL 输出）。
- test_context_formal_benchmark.py / test_quality_baseline.py — **eval/CI**（层外）。

## 关键命名修正（必须体现在 OWNERSHIP.md 与 spec）

1. `tests/runtime/` 最误导：测的是 `agent_runtime.py`（coordinator）+ observers = **Harness**，不是 Kernel "core runtime"。
2. `tests/session_runtime/` 是 **Harness 持久化**，不是 agent runtime。
3. `tests/integration/test_agent_core_runtime.py` 名字带 "core runtime"，实际 **Mixed（kernel+harness+capability）**。
4. `<relevant-memory>`（`tests/memory_runtime/test_injector.py`、`test_core_integration.py`）→ **capability[Memory]**。
5. Plan reset（`test_plan_runtime.py`、`tests/tooling/test_agent_runtime.py` plan-mode 部分）→ **capability[Plan]**。
6. MCP（`test_mcp_client.py`、`test_mcp_adapter.py`、`test_tool_environment.py`）→ **capability[MCP]**。
7. SubAgent（`test_agent_internal_runtime.py` 部分、`test_capability_runtimes.py`、`test_tool_selection.py`、`test_skill_registry_view.py`）→ **capability[SubAgent/Skill]**。

## 层分布汇总

- **Kernel（纯）**：tests/core/*、tests/context/*、tests/providers/*、test_usage.py、test_agent_run.py（为主）、test_model_query.py。
- **Harness**：tests/adapters/、tests/session_runtime/*、tests/runtime/*（renderer+usage observer）、tests/tooling/*（大部）、tests/application/*（facade）、test_hooks.py、test_provider_manager.py、test_project_identity.py、test_prompt.py、tests/tui/*（大部）。
- **Capability**：tests/capabilities/*、tests/memory_runtime/*、test_plan_runtime.py、test_mcp_client.py、test_session_memory*.py、application/test_skill_commands.py、tests/tooling/*（skill/subagent/mcp/plan-tools 文件）。
- **Supervisor**：test_autonomy.py、test_autonomy_flow.py、test_autonomy_goal_loop.py、test_dream.py、test_learning.py、integration/test_application_coding_session.py + application/test_coding_session_ports.py 的 overflow-retry 部分。
- **Product integration**：tests/tui/test_tui_app.py、test_cli.py、tests/integration/*（Mixed）。
- **Eval/CI infra（层外）**：tests/benchmarks/*、test_context_formal_benchmark.py、test_quality_baseline.py。
