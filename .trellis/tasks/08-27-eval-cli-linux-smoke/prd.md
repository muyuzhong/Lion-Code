# 组合单命令评测与 Linux 单题闭环

## Goal

提供一个薄命令，用指定 commit 和一条 SWE-bench Verified instance 串联已有执行、正式评分、
DeepEval 分析和 Opik 发布，并输出可复核报告。

## Background

- 必须等待 08-27-verified-execution-chain 与 08-27-eval-analysis-observability 完成。
- 本任务只做组合和真实验收，不重新实现任何 runner、scorer 或 publisher。

## Requirements

1. 一个共享 Python 函数按固定顺序组合既有模块；CLI 只负责解析参数、退出码和报告路径。
2. 输入至少固定 commit SHA、instance、profile、输出目录和 run_id；结果写严格 JSON 与中文 Markdown。
3. 报告同时区分 Harbor reward、官方 Harness、DeepEval 和 Opik 状态，并展示 digest、成本、耗时和非敏感引用。
4. 在 Linux Docker 服务器完成一条真实单题闭环，保留可复核命令和产物。
5. 任一分析/上传失败不能抹掉已完成的官方结果；infra 失败不计 0 分。

## Acceptance Criteria

- [ ] 一个命令可完成单条 Verified 流程并返回稳定退出码。
- [ ] JSON 能按严格模型读取，中文报告能定位四段结果及失败归属。
- [ ] 测试证明 CLI 与 DeepEval pytest 入口不会重复运行 Agent。
- [ ] Linux smoke 留下 commit、instance、依赖/镜像 fingerprint、Harness 结果、DeepEval 指标和 Opik trace_id。
- [ ] 默认项目 CLI、桌面和生产依赖不受影响。

## Out of Scope

- 批量、并发、定时任务、队列、CI gate、baseline/candidate 自动比较、Web UI。
- 通用工作流引擎、插件系统、自动选择数据集/模型、跨运行数据库。
- MVP 不实现通用 checkpoint/resume；失败重试使用各层已有产物和明确命令。

## Dependencies

- 08-27-verified-execution-chain 完成。
- 08-27-eval-analysis-observability 完成。
