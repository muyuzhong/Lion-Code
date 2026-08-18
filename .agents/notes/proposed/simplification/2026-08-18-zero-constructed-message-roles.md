# Agent Note: 删除零构造的 BashExecutionMessage / BranchSummaryMessage / CompactionSummaryMessage 角色

- Status: proposed
- 日期: 2026-08-18
- 范围: `lion_code/core/messages.py`、`lion_code/core/__init__.py`、`lion_code/tui/state.py`、`tests/core/*`（若有用例）

## Problem

`AgentMessage` 判别联合里三个角色从未被构造过：

- `BashExecutionMessage`（`core/messages.py:196-205`）、`BranchSummaryMessage`
  （:221-226）、`CompactionSummaryMessage`（:228-232）——`rg` 全仓（生产与测试）
  没有任何 `BashExecutionMessage(`/`BranchSummaryMessage(`/
  `CompactionSummaryMessage(` 构造点；线角色字符串 `"bashExecution"`/
  `"branchSummary"`/`"compactionSummary"` 在全仓其他任何地方都不出现。
- 它们只在三个地方被"处理"：`__all__`/union 成员（:239-241 与
  `core/__init__.py:34-36` 导出）、`message_text` 分支（:273-275）、
  `tui/state.py:313-319` 的 isinstance 分支——都是不可达分支。
- 重放层刻意归一化：`core/session/memory.py:112-156` 对两类 summary 一律合成
  普通 `UserMessage`；bash 结果经工具运行时成为 `ToolResultMessage`。

## Proposal

1. 删除三个类、union 成员、导出与 `message_text`/`tui/state.py:313-319` 分支。
2. 若 `tests/core/` 存在针对这三个角色的构造/序列化用例一并删除。

## Why not keep it

这三个角色对应 Pi 线格式里可能出现的角色——但仓库里既没有生产者也没有持久化
样本，且迁移层把任何外部 legacy 形状归一化掉了（`session_runtime/legacy.py` 只读
迁移 + `memory.py` 合成 UserMessage）。保留它们只是在判别联合上多三个不可达分支
与三次类型宽度。

## Acceptance criteria

- `rg -n "BashExecutionMessage|BranchSummaryMessage|CompactionSummaryMessage|bashExecution|branchSummary|compactionSummary" lion_code tests` 零命中。
- 全量可跑 unittest 通过（含 message 序列化/反序列化用例）。

## Risks

- 若外部消费者直接喂入含这些角色的 JSONL（绕过迁移层），反序列化会失败——当前
  canonical 入口（`SessionRepository` 重放）都经归一化迁移，风险低；文档中不把
  这些角色声明为受支持输入即可。