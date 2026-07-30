# 构建自建端到端任务集

## Goal

构建 30 条可复现、跨文件且防泄漏的 Lion 编码任务，作为快速回归与无偏 holdout 的来源。

## Requirements

- 跨文件重构、缺陷修复、特性开发各 10 条；每题独立 task card、base revision、公开任务说明、私有 verifier/gold 和资源元数据。
- 任务准入必须有 base fail、gold pass、稳定性、泄漏审查和来源证据。
- 固定 18 条 regression、12 条 holdout；调优或失败回流后的任务不可再用作 holdout。

## Acceptance Criteria

- [ ] 30 条 catalog 条目全部可通过结构与 split 校验。
- [ ] 每条任务保留 base/gold 可执行证据及 verifier/gold 哈希。
- [ ] 自动测试证明 split 防泄漏、重复 ID、缺失证据和不稳定任务均被拒绝。
- [ ] 中文任务构造说明可解释任务来源、分类和局限。

## Dependency

依赖 foundation 的 catalog/容器/verifier 契约。
