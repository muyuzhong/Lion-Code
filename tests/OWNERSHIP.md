---
schema: test-ownership/v1
layers:
  kernel: "Kernel 契约测试（Agent Loop/Turn/Session/Provider Port/Context/Usage）"
  harness: "Harness 契约测试（ProviderManager/ToolRuntime/Middleware/Permission/Session 持久化/Observer）"
  capability: "Capability 契约测试（Skill/Plan/SubAgent）"
  supervisor: "Supervisor 契约测试（Goal/Scheduler/Retry/Checkpoint）"
  product: "Product integration（完整应用端到端）"
  eval: "Eval/CI infra（层外：评测/门禁/质量工具）"
  mixed: "跨层（见备注中的主层与混合原因）"
---

# Test Ownership

单一权威的测试→四层归属清单。来源：`08-14-pr0-boundary-audit` 全量测试审计
（见 `.trellis/tasks/08-14-pr0-boundary-audit/research/test-ownership-map.md`）。

- 目录内归属一致的：一行一个目录，覆盖该目录全部文件（含 `__init__.py`、fakes、fixtures）。
- 目录内 mixed 的：按文件列出，标注主层与混合原因。
- 本清单只重定义归属，不移动、不删除任何测试文件。

## 目录级归属（归属一致）

| 测试文件/目录 | Layer | 备注 |
|---|---|---|
| tests/architecture/ | eval | 门禁元测试（边界强制 AST/行为测试），非层测试；`_boundaries.py` 是辅助模块 |
| tests/core/ | kernel | 纯 Kernel。AgentHarness 循环、取消、provider events。名字准确 |
| tests/context/ | kernel | Context Window / Compaction / projection / policy |
| tests/providers/ | kernel | Provider Port 实现（Anthropic/OpenAI/fake/stream/limits/thinking/factory） |
| tests/adapters/ | harness | Tool 协议适配（adapt_lion_tool/to_core_result/adapt_active_tools） |
| tests/runtime/ | harness | **名字误导**：测 `agent_runtime.py`（coordinator）+ observers（TerminalRenderer/UsageObserver），非 Kernel core runtime |
| tests/session_runtime/ | harness | SessionRecorder / SessionRepository / JSONL 持久化，**非 agent runtime** |
| tests/capabilities/ | capability | Capability SPI（registry/runtime/migration） |
| tests/benchmarks/ | eval | 评测/基准基础设施（层外） |

## 文件级归属（目录内 mixed）

### tests/application/

| 测试文件/目录 | Layer | 备注 |
|---|---|---|
| tests/application/fakes.py | harness | 确定性后端 fixture（不 import Agent） |
| tests/application/test_coding_session_ports.py | mixed | harness+supervisor：应用 facade/ports + overflow retry 编排 |
| tests/application/test_provider_settings.py | harness | Provider settings facade |
| tests/application/test_skill_commands.py | capability | Skill 能力路由 |

### tests/tooling/

| 测试文件/目录 | Layer | 备注 |
|---|---|---|
| tests/tooling/test_registry.py | harness | ToolRegistry |
| tests/tooling/test_runtime.py | harness | ToolRuntime 执行循环 |
| tests/tooling/test_hook_middleware.py | harness | Hook middleware |
| tests/tooling/test_permission_middleware.py | harness | Permission middleware（通用安全语义；PR4 移除 Plan/Auto 特判） |
| tests/tooling/test_permission_policy.py | harness | Permission policy（通用规则；PR4 移除 plan_file_path） |
| tests/tooling/test_concurrency_policy.py | harness | execution policy |
| tests/tooling/test_result_policy.py | harness | execution policy |
| tests/tooling/test_read_freshness.py | harness | 读取新鲜度 |
| tests/tooling/test_tool_search.py | harness | 工具搜索 |
| tests/tooling/test_builtin_tools.py | harness | 内置工具 |
| tests/tooling/test_agent_runtime.py | mixed | harness+capability[Plan]：Agent._execute_tool_call + plan-mode toggle |
| tests/tooling/test_agent_internal_runtime.py | mixed | harness+capability[SubAgent] |
| tests/tooling/test_capability_runtimes.py | capability | SkillRuntime / SubagentExecutor |
| tests/tooling/test_tool_selection.py | mixed | harness+capability[SubAgent] |
| tests/tooling/test_internal_tools.py | mixed | harness+capability[Skill/Plan/SubAgent] |
| tests/tooling/test_skill_registry_view.py | mixed | capability[Skill/SubAgent]+harness |

### tests/integration/

| 测试文件/目录 | Layer | 备注 |
|---|---|---|
| tests/integration/test_agent_core_runtime.py | mixed | **名字误导**：Kernel(loop/compaction/usage/budget/cancellation/tool-call) + Harness(ToolRegistry/ToolRuntime/SessionRepository/SessionRecorder/ProviderManager) + Capability[Plan/SubAgent] + Supervisor 重试，非纯 Kernel |
| tests/integration/test_application_coding_session.py | mixed | kernel+harness+supervisor：LionCodingSession，含 overflow auto-retry/recovery 编排 |
| tests/integration/test_core_tool_runtime.py | mixed | kernel+harness：AgentHarness→ToolRuntime→LionTool |
| tests/integration/test_meta_agent.py | mixed | kernel+harness：zero-extension MetaAgent、Event Stream、Session 与显式 Coding Tool composition |
| tests/integration/test_provider_core_tool_runtime.py | mixed | kernel+harness：真实 OpenAICompatibleProvider + httpx.MockTransport |

### tests/tui/

| 测试文件/目录 | Layer | 备注 |
|---|---|---|
| tests/tui/test_tui_adapter.py | harness | 事件→UI 适配 |
| tests/tui/test_tui_app.py | product | 完整 Textual 应用 + 真实 Agent（product integration） |
| tests/tui/test_tui_autocomplete.py | harness | TUI 组件 |
| tests/tui/test_tui_config.py | harness | TUI 组件 |
| tests/tui/test_tui_file_drop.py | harness | TUI 组件 |
| tests/tui/test_tui_themes.py | harness | TUI 组件 |

## 顶层测试文件

| 测试文件/目录 | Layer | 备注 |
|---|---|---|
| tests/test_agent_run.py | kernel | Agent.run() 契约；接线 SessionRepository(=Harness) 但断言 Kernel 不变量 |
| tests/test_supervisor.py | supervisor | Goal / retry / checkpoint lifecycle |
| tests/test_context_formal_benchmark.py | eval | 上下文评测（层外） |
| tests/test_hooks.py | harness | permission/safety/hooks/execution backend |
| tests/test_plan_runtime.py | capability | Plan（事务/审批/View；PR3 移除 pending reset，PR4 移除权限模式耦合） |
| tests/test_project_identity.py | harness | identity/config |
| tests/test_prompt.py | harness | prompt composition |
| tests/test_provider_manager.py | harness | ProviderManager |
| tests/test_quality_baseline.py | eval | 质量基线（层外） |
| tests/test_ui.py | harness | REPL 输出 |
| tests/test_usage.py | kernel | Usage/Budget 语义 |

## 命名修正要点

以下文件/目录名字带 "runtime"/"core runtime"，但**不属于 Kernel**；归属已被清单重定义：

1. `tests/runtime/` → **harness**。测的是 `lion_code/agent_runtime.py`（coordinator）+ observers，
   不是 Kernel "core runtime"。
2. `tests/session_runtime/` → **harness**。是 SessionRecorder/SessionRepository/JSONL 持久化，
   不是 agent runtime。
3. `tests/integration/test_agent_core_runtime.py` → **mixed**。名字带 "core runtime"，
   实际含 Kernel + Harness + Capability[Plan/SubAgent] + Supervisor 重试。
4. Plan 事务（`tests/test_plan_runtime.py`、`tests/tooling/test_agent_runtime.py` plan-mode 部分）
   → **capability[Plan]**。clear-and-execute 的 pending context reset 与
   `apply_plan_context_reset` 已随 PR3 从 Kernel/Runtime 移除，集成测试标记 skip 待 re-home。
   PR4 进一步移除 Plan 与 Permission 的耦合：PermissionMode 不含 plan/auto，
   ToolContext 无 plan / auto_permission_fn，PermissionMiddleware/Policy 无 plan/auto 特判，
   PlanRuntime 不再写 PermissionController；产品策略（PlanRestrictedPolicy /
   LLMPermissionPolicy）留待后续 PR 由 Composition 注入。
5. SubAgent/Skill（`tests/tooling/test_capability_runtimes.py`、
   `tests/tooling/test_tool_selection.py`、`tests/tooling/test_skill_registry_view.py`、
   `tests/tooling/test_agent_internal_runtime.py` 部分）→ **capability[SubAgent/Skill]**。

"core runtime 必须行为"措辞已废弃，替换为"Kernel 不变量"。

## 层分布汇总

- **Kernel（纯）**：tests/core/、tests/context/、tests/providers/、test_usage.py、
  test_agent_run.py（为主）。
- **Harness**：tests/adapters/、tests/session_runtime/、tests/runtime/
  （renderer+usage observer）、tests/tooling/（大部）、tests/application/（facade）、
  test_hooks.py、test_provider_manager.py、test_project_identity.py、test_prompt.py、
  tests/tui/（大部）。
- **Capability**：tests/capabilities/、test_plan_runtime.py、
  application/test_skill_commands.py、
  tests/tooling/（skill/subagent/plan-tools 文件）。
- **Supervisor**：test_supervisor.py、application/test_coding_session_ports.py 的
  overflow-retry 部分。
- **Product integration**：tests/tui/test_tui_app.py、tests/integration/（Mixed）。
- **Eval/CI infra（层外）**：tests/architecture/、tests/benchmarks/、
  test_context_formal_benchmark.py、test_quality_baseline.py。
