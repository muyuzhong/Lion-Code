# Agent Note: 删除 LionTool.label 只写字段（agenttool-unread-surface 遗留核对项）

- Status: proposed
- 日期: 2026-08-29
- 范围: `lion_code/tooling/types.py`、`lion_code/tooling/builtin.py`、`lion_code/tooling/internal.py`、`lion_code/capabilities/memory/capability.py`

## Problem

`LionTool.label`（`tooling/types.py:75`）是一个只写字段：13 个写入点（`builtin.py:54`；`internal.py:17,52,82,100,136`；`memory/capability.py:225,272,346,394,429,585,613,649`）之后没有任何读取者：

1. 生产读取者：无——`rg "\.label"` 在 `lion_code/**` 的全部命中是 session 重命名/UI spinner/hook/theme 的 label，没有任何一处读 `tool.label`；`tool_adapter.py` 的 schema 组装、provider 载荷、TUI 展示均用 `name`。
2. 测试/文档消费者：无——`test_builtin_tools.py` 只断言 schema 与 name，不读 label。

这正是 `agenttool-unread-surface`（PR #52）明示「需先核对」而当时未删的同域残留；本次核对结论：零读取。

## Proposal

删除 `LionTool.label` 字段及上述 13 个构造点传参（`label=...` → 删除）；无测试/文档引用需同步。

## Why not keep it

label 是「工具显示名」语义字段，但任何现有面都用 `name` 展示。按「没有读取者就不存在」与 `agenttool-unread-surface` 先例删除；若未来 TUI/侧边栏要展示人类可读名，从 `name` 派生或加回字段成本对称。

## Acceptance criteria

- `rg -n "\.label\b" lion_code/tooling/ lion_code/adapters/` 零命中（除 session label 等无关命中外）。
- `tests/tooling/`、`tests/adapters/` 全绿。

## Risks

- 若未来工具需要「展示名 ≠ 调用名」，需重新加字段与 13 个传参——当前无消费者，风险低。