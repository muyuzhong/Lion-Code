# 自建历史回放任务集设计

## Scope

本子任务把 Lion 的真实历史提交整理为 30 条版本化任务卡：跨文件重构、缺陷修复、特性开发各 10 条。公开 catalog 只提供 base revision、公开说明、资源和 gold patch hash；gold commit、provenance verifier 和 preflight 元数据位于 evaluator 私有侧，不能进入 Agent workspace。

V1 的每题来自一个已有 Git commit。它的准入证据是可执行的 historical patch-replay：确认 base 与 gold 不同、从 Git 重新计算 binary diff 的 SHA-256、检查 patch 格式，并以相同输入重复三次得到一致结果。该证据证明任务重放与 gold 来源可复现，但不是语义 hidden-test 的替代品；真实 Docker backend 上线前不得把该 corpus 的 patch-equivalence 结果发布为官方成功率。

## Split and leakage rule

- 共 30 条，`cross_file_refactor`、`bugfix`、`feature` 各 10 条。
- regression 为 18 条：4 条重构、9 条缺陷修复、5 条特性；holdout 为 12 条：6 条重构、1 条缺陷修复、5 条特性。
- 历史提交链不可跨 split：任一题的 base revision 或 gold commit 不得出现在另一 split 的 gold/base 中。
- 反馈回流任务 ID 不能进入 holdout；已进入 regression 的 task 仍可保留历史证据，但不得被重新标为 holdout。

## Boundaries

- `benchmarks/agent_e2e/corpus.py` 负责公开 catalog、private evidence 的装配、准入校验和纯 Git provenance preflight。
- public TaskSpec 仅包含 `gold_evidence_hash`，不暴露 gold commit、private verifier 命令或完整 patch。
- private evidence 必须和 public task ID 一一对应，hash 与 TaskSpec 一致，且记录 base fail、gold pass、三次稳定结果与 leakage review。
- 历史回放的 Agent workspace 不能直接复用 evaluator 的完整 Git worktree：运行时只交付被选中的单题卡和 base tree 快照，避免 Git object database 暴露同一提交链中的 gold。
- Git 历史不可用、patch hash 不匹配、preflight 非稳定或 split 交叉污染都属于拒绝准入，而非可忽略警告。

## Tests

- 断言 bundled catalog 的 30 条、三类配额、18/12 split、public/private 一一对应。
- 断言重复 ID、缺失 evidence、不稳定 preflight、feedback/holdout 交集和跨 split commit 链均被拒绝。
- 对代表任务执行真实 Git provenance preflight；全量 corpus 在本机历史可用时执行三轮检查。
- 中文说明列出来源、分类、preflight 口径和 V1 局限。
