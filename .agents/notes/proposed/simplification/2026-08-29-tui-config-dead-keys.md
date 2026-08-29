# Agent Note: 删除 TUI 配置残键（sidebar_position / auto_copy_selection）

- Status: proposed
- 日期: 2026-08-29
- 范围: `lion_code/tui/config.py`、`tests/tui/test_tui_config.py`

## Problem

`TuiSettings` 的两个持久化配置键没有任何生产消费者：

1. **`sidebar_position`**（`config.py:92` 字段、`:100` `to_json`、`:150-152` 解析 + :167 严格校验）：侧边栏子系统已由笔记 PR#50（`tui-dead-sidebar-and-render-chat-item`）删除，但本键残留——生产 TUI 零读取（`#sessions` ListView 固定左侧，app.py CSS :705-709；`action_toggle_sidebar` :1304-1306 只切 display，不读该键）。消费者只有 `tests/tui/test_tui_config.py:216-233`（默认值/roundtrip/非法值三用例）。
2. **`auto_copy_selection`**（`config.py:91`、`:98`、`:163-166`）：TUI 无任何自动复制逻辑（rg clipboard/copy 只命中 `copy_message` 键，其为 clear_prompt 绑定，见 TODO）；消费者只有 `tests/tui/test_tui_config.py:150-159,187`。

两键都是「读盘、校验、落盘三处代码服务一个已不存在/未接线的功能」。

## Proposal

1. 删除 `sidebar_position`：字段、`to_json` 键、解析与校验分支（`config.py:92,:100,:150-152,:167`）；同步删 `tests/tui/test_tui_config.py:216-233`。
2. 删除 `auto_copy_selection`：字段、`to_json` 键、解析与 `_bool_setting` 分支（`config.py:91,:98,:163-166`）；同步删 `tests/tui/test_tui_config.py:150-159,187`。

## Why not keep it

属于「已删功能的配置残留」与「上游 Tau 预留无接线」两类；按 AGENTS.md「不保留向后兼容 + 不为假设预留」删除。未来若恢复可配置侧栏或复制选中，重加成本与删除对称（各 3 行 + 测试）。

## Acceptance criteria

- `rg -n "sidebar_position|auto_copy_selection" lion_code/ tests/ desktop/` 零命中（除 docs 如需同步）。
- `tests/tui/test_tui_config.py` 全绿；`tui_settings_from_json` 对未知键仍静默忽略（现有行为），对删后键的非法值不再校验属预期。

## Risks

- 用户既有 `~/.lion-code/tui.json` 若含这两个键，升级后静默忽略（与现状对未知键的处理一致），无兼容负担。