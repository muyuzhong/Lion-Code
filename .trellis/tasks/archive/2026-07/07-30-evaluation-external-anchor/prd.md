# 接入 SWE-bench-Live 外部锚点

## Goal

以 20 条冻结的 SWE-bench-Live Python 实例校验 Lion 自建评测的外部有效性，而不是将外部数据误当作日常低成本 CI。

## Requirements

- 选择 manifest 记录数据集 revision、split、平台、分层规则、seed 与 20 个 instance ID。
- 每条实例先经 gold patch 三次预检，只有当次稳定有效的实例进入实际分母。
- 调用官方 patch evaluator，保存无敏感的结果、镜像和 invalid 原因，并接入统一 TaskResult/report。
- 对至少五个冻结 profile 计算外部与自建 holdout 的排名/方向一致性。

## Acceptance Criteria

- [x] Docker/数据集不可用时返回 blocked，绝不构造外部通过率。
- [x] 选择、gold 预检、实际 denominator、patch evaluator 输出均可复跑。
- [x] 报告给出外部通过率、区间、无效项、profile 指纹和校准结论。
- [x] 数据集/镜像/平台漂移阻止与旧 baseline 的错误比较。

## Dependency

依赖 foundation；正式运行还依赖可用 Docker daemon 与显式预算/凭证。

## 本机执行状态

实现、静态清单与回归已完成；本机 Docker daemon 不可用，因此没有真实外部通过率。该状态由
`UnavailableOfficialSWEbenchLiveRunner` 明确表示为 `blocked`，不是 0% 或失败结果。
