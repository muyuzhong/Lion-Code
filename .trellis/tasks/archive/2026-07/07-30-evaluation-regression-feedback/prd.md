# 建立回归门禁与失败回流

## Goal

把 prompt、压缩与工具变更转为可审计的回归判定，并让被验证的失败轨迹安全地扩充未来评测集。

## Requirements

- 同一 catalog/profile/seed/资源限制下比较 baseline 与 candidate，输出 pass、reject、invalid 或 waived。
- 判定覆盖非劣边界、灾难性回退、有效分母和不可比结果；仅 reject 且未合入计入拦截账本。
- 受控 trace 提供死循环、上下文腐烂、工具误用、过早终止的候选标签与 evidence offset。
- failure triage 支持复现、去重、责任判断和 regression/holdout 回流防泄漏。

## Acceptance Criteria

- [x] 规则测试覆盖四类失败、基础设施隔离、判定状态和账本计数。
- [x] 一次故意劣化候选被 gate 拒绝并写入可审计 ledger。
- [x] 至少一条已复现失败通过审查后回流为 regression，且无法继续作为 holdout。
- [x] 未完成外部校准时，报告不会把 self-only gate 宣称为泛化质量证明。

## Dependency

依赖 foundation 与 task corpus；强制 gate 的外部有效性结论依赖 external anchor 校准。
