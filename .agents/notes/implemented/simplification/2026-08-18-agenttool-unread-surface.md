# Agent Note: 删除 AgentTool 上无人读取的渲染/准备/展示面

- Status: proposed
- 日期: 2026-08-18
- 范围: `lion_code/core/tools.py`、`lion_code/adapters/tool_adapter.py`、`lion_code/core/loop.py`、`tests/core/test_harness.py`、`tests/adapters/test_tool_adapter.py`

## Problem

`AgentTool`（`core/tools.py`）保留了一批「工具自渲染/自准备」的迁移残留，
全部是写而无人读（或读而无人写）：

1. **渲染面**：`ToolCallRenderer`/`ToolResultRenderer` 协议（:45-54）、
   `render_call`/`render_result` 字段（:89-90）——`rg` 全仓零读取零调用；
   TUI 的前端渲染在 `tui/` 自行实现（`tui/state.py`/`widgets.py` 的 ChatItem
   renderers），按 `four-layer-ownership.md` 前端渲染本来就属于前端。
2. **展示元数据**：`label`（:81）、`prompt_snippet`（:85）、`prompt_guidelines`
   （:86）——唯一写入点 `adapters/tool_adapter.py:87,91,92` 从 `LionTool` 拷贝，
   之后没有任何生产代码读取（prompt 组装、providers、TUI 都不用）。
3. **参数准备**：`ToolArgumentPreparer`（:73）+ `prepare_arguments`（:87）——
   `core/loop.py:493-497` 会调用它，但没有任何生产工具设置它
   （唯一设置在 `tests/core/test_harness.py:272`）；工具参数策略实际由
   tooling middleware 承担。

## Proposal

1. 删除两个渲染协议与 `render_call`/`render_result` 字段。
2. 删除 `label`/`prompt_snippet`/`prompt_guidelines` 字段及
   `tool_adapter.py:87,91,92` 的拷贝行；若 `LionTool`（`tooling/types.py`）上
   同名字段也无读取者则一并删除（需先核对 tooling 文档/技能注册查看是否引用）。
3. 删除 `prepare_arguments`/`ToolArgumentPreparer` 与 `core/loop.py:493-497`
   的调用分支（含测试 `test_harness.py:272` 与
   `tests/adapters/test_tool_adapter.py:70-73` 的拷贝断言改造）。

## Why not keep it

工具自渲染是「工具拥有 UI」的投机泛化——`four-layer-ownership.md` 明确定义
渲染归前端；准备参数的职责已被 middleware 接管。这些面从 Core 迁移期存活至今，
零消费者，删掉后 `AgentTool` 只剩 providers 真正需要的 `parameters`/`input_schema`
等字段，模型更小、契约更准。

## Acceptance criteria

- `rg -n "render_call|render_result|ToolCallRenderer|ToolResultRenderer|prepare_arguments|ToolArgumentPreparer|prompt_snippet|prompt_guidelines" lion_code tests` 零命中（保留 `tool_adapter.py` 的 `ToolResult`/`LionTool` 本体）。
- 工具执行集成测试（`test_core_tool_runtime`/`test_builtin_tools`）全绿；
  全量可跑 unittest 通过。

## Risks

- `label`/`prompt_snippet`/`prompt_guidelines` 若被 `LionTool` 契约外的工具注册
  文档（如 Skill 元数据渲染）引用则需保留——实施前先核对
  `tooling/registry.py`/`application/skills.py` 的读取点；本提案已在范围内列明。

## 落地

- 提交: `1c0eda50b06f93558629b6aeded64a14bc9003ad`（squash merge）
- PR: #52（标题：refactor: 删除 AgentTool 无人读取的渲染/准备/展示面）
- 门禁证据: 定向测试全绿（排除 5 个已知环境性/既有失败：test_coding_session_ports、test_composition_profiles::test_all_profiles_return_meta_facade、test_capability_migration::test_session_participant、test_agent_core_runtime::test_plan_clear、test_cli::test_repl_routes_generic_command）；CI Quality gates 已通过（2026-08-18）。
