# Agent Note: 删除 TUI 自定义主题管线与 application/resources.py（tests-only 链条）

- Status: proposed
- 日期: 2026-08-29
- 范围: `lion_code/application/resources.py`、`lion_code/tui/themes/__init__.py`、`tests/tui/test_tui_themes.py`、`tests/tui/test_tui_config.py`

## Problem

一条「磁盘扫描自定义主题 → 诊断上报 → 注册」管线只有测试在消费，生产零接线：

1. `load_custom_tui_themes`（`tui/themes/__init__.py:404-458`）与 `set_custom_tui_themes`（:386-389）及 `_custom_themes` 槽（:383）：全仓调用点只有 `tests/tui/test_tui_themes.py`（约 7 个自定义主题用例）；生产路径 TUI `app.py` 只用 `available_tui_theme_names()`/`get_tui_theme()` 的内置分支（`:772-775,:837,:1223,:1263-1267`），没有任何进程内路径把 `theme_dirs` 传给加载器——`_custom_themes` 运行时恒为空，`get_tui_theme` 的自定义回退（:401）与 theme picker 的自定义项生产不可达。
2. `application/resources.py` 整模块（`ResourceError` :13、`ResourceDiagnostic` :18-35）：`ResourceError` 全仓（含测试）零引用；`ResourceDiagnostic` 唯一消费者就是上述加载器（构造于 :423/:434/:449，`format()` 与 `severity` 也零调用）。
3. `themes/__init__.py` 的 docstring（:5）仍写 `~/.tau/themes` 用户目录（Tau 残留，Lion home 实为 `~/.lion-code`）。

## Proposal

1. 删除 `load_custom_tui_themes`/`set_custom_tui_themes`/`_custom_themes` 与 `get_tui_theme` 的自定义分支（保留内置三主题加载 `_load_builtin_theme`/`parse_tui_theme_json`/`available_tui_theme_names` 内置部分）。
2. 删除 `application/resources.py` 整模块；同步删除 `tui/themes/__init__.py:24` 的 import。
3. 同步删除 `tests/tui/test_tui_themes.py` 的自定义主题与 diagnostics 用例（保留内置主题用例）。
4. 修正 `themes/__init__.py` docstring 的 `~/.tau` 残留文案。

## Why not keep it

TUI 已有 `/theme` picker 与三个内置主题，用户自定义主题目录是「未接线的载荷」：保留它只扩大维护面（磁盘扫描、冲突诊断、JSON 解析错误处理都有专门代码），而没有任何生产入口。按 AGENTS.md 原则 2（不为未来假设预留），删除成本与重建成本对称。

## Acceptance criteria

- `rg -n "load_custom_tui_themes|set_custom_tui_themes|_custom_themes|ResourceDiagnostic|ResourceError" lion_code/ tests/` 零命中。
- `tests/tui/` 全绿；`app.py` 的 theme picker 仍列三个内置主题。

## Risks

- 若未来产品要做「服务端注入自定义主题」，需要重建加载器+诊断类型（约 75 行 + 测试）——当前无任何接线，风险可接受。