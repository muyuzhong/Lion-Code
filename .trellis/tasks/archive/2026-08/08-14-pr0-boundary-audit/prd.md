# PR0 边界审计与测试重新分类

## Goal

审计真实代码/现有测试的四层边界归属，重新分类"core runtime"测试，产出可执行的测试→四层归属清单，并更新 spec。`<relevant-memory>`、Plan reset、MCP、SubAgent 等**不得再定义为 Core Runtime 必须行为**。

## 现状（已核实：108 个测试文件全部审计）

### 归属结论（来自全量测试审计）

| 测试目录/文件 | 实际层 | 说明 |
|---|---|---|
| `tests/core/` | **Kernel（纯）** | AgentHarness 循环、取消、provider events。名字准确 |
| `tests/context/` | **Kernel** | Context Window / Compaction / projection |
| `tests/providers/` | **Kernel** | Provider Port 实现（Anthropic/OpenAI/fake/stream/limits） |
| `test_usage.py` | **Kernel** | Usage/Budget 语义 |
| `test_agent_run.py` | **Kernel（为主）** | Turn/Session 语义、cancellation、usage（接线了 SessionRepository=Harness，但断言 Kernel 不变量） |
| `test_model_query.py` | **Kernel** | Provider 端口薄包装 |
| `tests/runtime/` | **Harness（名字误导！）** | `agent_runtime.py`（coordinator）+ observers，不是 Kernel "core runtime" |
| `tests/session_runtime/` | **Harness** | SessionRecorder / SessionRepository / JSONL 持久化 |
| `tests/adapters/` | **Harness** | Tool 协议适配 |
| `tests/tooling/`（大部） | **Harness** | ToolRegistry / ToolRuntime / Middleware / Permission / execution policy |
| `tests/application/`（大部） | **Harness** | 应用 facade / ports / provider settings |
| `test_hooks.py`、`test_provider_manager.py`、`test_project_identity.py`、`test_prompt.py`、`tests/tui/`（大部） | **Harness** | hooks / ProviderManager / identity / prompt / TUI 组件 |
| `tests/capabilities/` | **Capability** | Capability SPI（registry/runtime/migration） |
| `tests/memory_runtime/` | **Capability** | Memory（含 `<relevant-memory>` 的 injector 测试） |
| `test_plan_runtime.py` | **Capability** | Plan（含 Plan reset 测试） |
| `test_mcp_client.py`、`test_session_memory*.py`、`application/test_skill_commands.py` | **Capability** | MCP / Memory / Skill |
| `tests/tooling/`（skill/subagent/mcp/plan-tools 文件） | **Mixed（Harness+Capability）** | 工具执行 + 能力路由 |
| `test_autonomy*.py`、`test_dream.py`、`test_learning.py` | **Supervisor** | Autonomy / Dream / Learning |
| `tests/integration/` | **Mixed（Kernel+Harness+部分Cap/Sup）** | 真实 Agent 全装配 |
| `tests/tui/test_tui_app.py`、`test_cli.py` | **Product integration** | 完整应用 |
| `tests/benchmarks/*`、`test_context_formal_benchmark.py`、`test_quality_baseline.py` | **Eval/CI infra（层外）** | 评测/质量工具 |

### 命名误导重点（本 child 必须修正）

- `tests/runtime/` 最误导：测的是 `lion_code/agent_runtime.py`（coordinator）+ observers = **Harness**，不是 Kernel "core runtime"。
- `tests/session_runtime/` 是 **Harness 持久化**，不是 agent runtime。
- `tests/integration/test_agent_core_runtime.py` 名字带 "core runtime"，实际 **Mixed（Kernel+Harness+Capability[Plan/SubAgent]+Supervisor 重试）**。
- `<relevant-memory>`（`tests/memory_runtime/test_injector.py`、`test_core_integration.py`）、Plan reset（`test_plan_runtime.py`、tooling plan-tools）、MCP、SubAgent 测试当前被当作 runtime 行为，实为 **Capability**。

## Requirements

### R1. 产出测试→四层归属清单（可执行）

- 单一权威清单：每个测试文件/目录 → 层（Kernel / Harness / Capability / Supervisor / Product integration / Eval infra / Mixed）。
- 清单为机器可读（如 TOML/JSON 或 markdown 表），供后续门禁校验（路径存在、无重复）。
- 不改动测试文件物理位置（受 R5"不进行大规模目录搬迁"约束）；用清单 + 文档重定义归属。

### R2. 修正 "core runtime" 误标签

- 明确 `tests/runtime/`、`tests/session_runtime/`、`tests/integration/test_agent_core_runtime.py` 的真实归属（Harness / Harness / Mixed），在 spec 与清单中修正。
- `<relevant-memory>`、Plan reset、MCP、SubAgent 相关测试标记为 Capability，不再归 Core Runtime 必须行为。

### R3. 更新 spec

- 在 `.trellis/spec/backend/` 增加/更新"四层归属"文档：Kernel/Harness/Capability/Supervisor 定义 + 每个模块/测试目录的归属 + `<relevant-memory>`/Plan reset/MCP/SubAgent 归属声明。
- 与现有 `runtime-boundaries.md`、`capability-spi.md` 一致，不冲突。

### R4. 实际边界发现

- 总结审计中发现的真实架构边界与"原方案 vs 真实代码"不一致点（供父任务最终总结）。

## Acceptance Criteria

- [ ] 归属清单文件存在，覆盖全部 108 个测试文件/目录，层归属明确。
- [ ] `tests/runtime/`、`tests/session_runtime/`、`tests/integration/test_agent_core_runtime.py` 的误导命名在清单/spec 中修正。
- [ ] `<relevant-memory>`、Plan reset、MCP、SubAgent 测试在清单中标记为 Capability。
- [ ] spec 增加四层归属文档，与现有 spec 一致。
- [ ] 未删除任何测试、未大规模搬迁（R5 遵守）。
- [ ] 现有测试全通过（本次只加文档/清单，不改行为）。

## Notes

- 清单文件路径与格式见 design。建议 `tests/OWNERSHIP.md`（人类可读 + 可校验表）+ 供门禁读取。
- 本 child 的归属结论是 08-14-pr0-architecture-gates 的输入。
