# PR4 执行计划

前置：master 已含 PR1–PR3（已核实 origin/master == PR3，本地仅多任务归档提交）。工作区已清理（平台配置改动已单独提交）。

## 步骤

### Step 1 — Feature 文件移动（纯移动，机械改 import）

1. 按移动表迁移 9 个文件到 feature package，建 `__init__.py`（导出各自公共符号）。
2. 更新全部 import：
   - `composition/agent_builder.py`（plan/skill/subagent 符号）
   - `capabilities/__init__.py`（收窄为 generic SPI）
   - `application/commands.py`、`application/session.py`、`__main__.py`（skills 发现）
   - 测试中的 `lion_code.plan_runtime` / `lion_code.skill_runtime` / `lion_code.subagent_runtime` / `lion_code.subagent_factory` / `lion_code.skills` / `lion_code.subagent` 模块路径与 monkeypatch 字符串（`tests/core/test_event_contract.py`、`tests/integration/test_agent_core_runtime.py`、`tests/tooling/test_agent_runtime.py`、`tests/tooling/test_skill_registry_view.py`、`tests/test_plan_runtime.py`、`tests/tooling/test_capability_runtimes.py`、`tests/tooling/test_tool_selection.py`、`tests/application/test_skill_commands.py`、`tests/test_cli.py`）
3. 删除 package root 旧文件。

验证：`py_compile` 全量 + `PYTHONPATH=tests python3 -m unittest discover tests -p "test_*.py"`。

### Step 2 — MetaAgent 通用缺口

新增 `queue_snapshot` / `compact_for_overflow` / `is_running` / `api_configured` / `provider_name`（各 1–3 行委托）。

验证：定向 `tests/runtime` + 全量 unittest。

### Step 3 — CodingSessionBackendAdapter + factory

1. 新建 `lion_code/adapters/coding_session_backend.py`：Adapter + `build_full_coding_backend`（平移旧 `Agent.__init__` 的 config/bindings 装配与产品方法）。
2. `__main__.py` 切换到 factory + Adapter（REPL `_dispatch_repl_command` 参数类型改为 Adapter）。
3. 单测：`tests/adapters/test_coding_session_backend.py`（protocol 结构化满足、MRO 无 MetaAgent、list_sessions/legacy 迁移、set_terminal_output 三路开关、show_cost）。

验证：定向测试 + `python -m lion_code --help` 冒烟。

### Step 4 — 删除 lion_code/agent.py + 测试迁移

1. 删除 `agent.py`。
2. 逐文件迁移 13 个测试：
   - `tests/test_agent_run.py`、`tests/test_cli.py`、`tests/test_hooks.py`、`tests/tui/test_tui_app.py`、`tests/integration/test_application_coding_session.py`、`tests/integration/test_agent_core_runtime.py`、`tests/benchmarks/test_agent_worker.py` → `build_full_coding_backend`
   - `tests/architecture/test_composition_profiles.py`、`tests/capabilities/test_capability_migration.py`、`tests/runtime/test_agent_runtime.py`、`tests/tooling/*` → 真实公共构造路径（`build_profile_agent`/`build_coding_agent`/`build_meta_agent`）
   - monkeypatch `lion_code.agent.*` seam → 真实路径（`lion_code.providers.factory.create_provider`、ConfirmationController 等）
3. 每迁一个文件跑其定向测试。

### Step 5 — Architecture tests（9 条验收）

新增 `tests/architecture/test_product_adapter.py`：
1. `lion_code.__all__` 与模块属性无 `Agent`
2. Adapter 满足 `CodingSessionBackend`（`isinstance(x, CodingSessionBackend)` runtime_checkable 或逐 port 方法存在性 + `_boundaries.py` helper）
3. `not issubclass(CodingSessionBackendAdapter, MetaAgent)` 且 MRO 检查
4. AST 扫描 `meta_agent.py`：方法/属性黑名单（list_sessions、restore_latest、show_cost、set_terminal_output、toggle_plan_mode、set_plan_approval_fn、set_notice_fn、set_confirm_fn、legacy 迁移符号）
5. `capabilities/types.py`/`registry.py`/`runtime.py` 的 import 集合不含 `plan`/`skill`/`subagent`，且 AST 无 feature 名称分支
6. feature 包文件树断言（`capabilities/plan/__init__.py` 等存在，旧路径不存在）
7. 沿用现有 application/tui→Harness 门禁（复核期望值）
8. `supervisor.py` import 集合不含 `lion_code.adapters`
9. 沿用 `test_composition_profiles.py`：三 Profile 构造结果类型一致（MetaAgent + 相同 Runtime 组合）

同步 `tests/architecture/_boundaries.py` / import-linter 配置（如涉及）。

### Step 6 — 残留扫描 + spec/docs 更新

1. 全仓扫描 prd.md R4 清单（排除 `.trellis/tasks/archive/`、`__pycache__`）。
2. 更新 `.trellis/spec/backend/` 相关 spec（目录树、公共 API、依赖图）与 `docs/` 中作为**当前架构**描述的旧路径；历史 archive 不动。
3. 更新 `docs/quality-baseline-2026-08.json` 漂移指纹。

### Step 7 — 全量验证 + 输出报告

1. 全量 unittest + quality gates（ruff/mypy/radon/vulture 对基线，命令见 AGENTS.md）。
2. 输出：调用链前后、目录树、移动表、公共 API、依赖图、residual scan、测试结果、封板结论与未来能力接入边界。

## 提交策略（每步一 commit，中文描述）

1. `refactor(capabilities): Plan/Skill/SubAgent 内聚为 feature package`
2. `refactor(meta_agent): 补齐通用对话/Provider 只读投影`
3. `feat(adapters): CodingSessionBackendAdapter 组合实现 + Full 产品构造入口`
4. `refactor: 删除 Agent 继承，迁移全部调用方与测试`
5. `test(architecture): Product Adapter / Feature Cohesion 门禁`
6. `docs(spec): 同步 PR4 架构事实与基线`

## 回滚点

每步独立 commit 可单独 revert；Step 3 之前 `agent.py` 全程可用。

## 完成记录（2026-08-20）

- Step 4–6 已完成：删除 `lion_code/agent.py`，迁移调用方与测试，增加
  Product Adapter / Feature Cohesion 架构门禁，同步目录、边界、运行时和
  code-spec 文档，并将历史 corpus 的 ACTIVE 资源指向当前适配器路径。
- Step 7 已完成：751 passed、3 skipped、10 subtests；ruff check 42/54、
  ruff format 68/79、mypy 35/68、radon 9/12、vulture 3/5，import-linter
  9/9 contracts kept，compileall 与 `python -m lion_code --help` 通过。
- 本轮未使用 subagent。
