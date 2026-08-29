# Agent Note: 删除 prompt template 恒空链（prompt_templates.py 模块 + 补全模板分支）

- Status: proposed
- 日期: 2026-08-29
- 范围: `lion_code/application/prompt_templates.py`、`lion_code/application/session.py`、`lion_code/application/commands.py`、`lion_code/tui/app.py`、`lion_code/tui/autocomplete.py`、`tests/tui/test_tui_autocomplete.py`

## Problem

prompt template 是一条自证「阶段 4 落地」但从未落地的恒空链，生产任何一端都没有真实数据：

1. **模块**：`application/prompt_templates.py` 仅定义 `PromptTemplate` 视图类型（:12-19），docstring 自述「发现与展开逻辑按迁移计划在阶段 4 落地」。
2. **恒空数据源**：`LionCodingSession.prompt_templates`（`application/session.py:285-287`）恒 `return ()`（注释明写「当前恒为空」）；`CommandSession.prompt_templates`（`commands.py:39`）是端口声明。
3. **空闲分支**：`tui/app.py:835` 把恒空元组喂给 `tui/autocomplete.py` 的模板补全分支（`:131, :311-315, :337-348`），对空输入恒不命中。
4. 消费者证据：`PromptTemplate(` 构造点全仓只有 `tests/tui/test_tui_autocomplete.py`（:88/:150/:162/:207/:226）；生产零构造；server 不提供模板接口；desktop 零引用。

## Proposal

1. 删除 `application/prompt_templates.py` 整模块。
2. 删除 `session.py:285-287` 的 `prompt_templates` 属性与 `commands.py:39` 端口声明。
3. 删除 `tui/autocomplete.py` 的模板补全分支与 `tui/app.py:835` 的传参。
4. 同步删除 `tests/tui/test_tui_autocomplete.py` 中 `PromptTemplate` 构造与模板补全用例。

## Why not keep it

「无消费者的默认值」最典型形态：vendored 占位类型 + 恒空数据 + 空闲分支三层叠在一起，全部只有测试钉住。按 AGENTS.md「不为假设预留配置层」，需要做 `/prompt` 模板命令时按现有接线模式加回成本很低。

## Acceptance criteria

- `rg -n "PromptTemplate|prompt_templates" lion_code/` 零命中（`application/__init__.py` 若导出需同步清理）。
- `tests/tui/test_tui_autocomplete.py` 与 `tests/application/` 全绿。

## Risks

- 未来若实现 `/prompt-template` 命令，需要重建视图类型与补全分支——当前未见产品诉求，风险可接受。