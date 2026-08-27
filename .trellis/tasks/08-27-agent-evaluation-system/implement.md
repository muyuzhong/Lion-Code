# Lion 自动化评测系统任务图

## 已完成

- 提交 425ef995：冻结 Verified、Harbor、Harness、DeepEval 与 Opik 的严格结果契约和离线 parser。

## 剩余子任务

1. 08-27-verified-execution-chain
   - 构建指定 commit 产物。
   - 在 Linux Harbor 运行一条 Verified 任务。
   - 用官方 Harness 对同一 patch 给出正式结果。
2. 08-27-eval-analysis-observability
   - 依赖子任务 1 的脱敏 trajectory 和正式结果。
   - 用 DeepEval 做三个固定离线指标。
   - 把同源 trace 与 feedback 后置发布到 Opik Cloud。
3. 08-27-eval-cli-linux-smoke
   - 依赖子任务 1 和 2。
   - 仅组合已有模块，提供单题命令、JSON/中文报告和 Linux 完整 smoke。

## 执行规则

- 严格按 1 → 2 → 3；父任务不再承载直接实现。
- 每个子任务独立 planning、check、中文提交和回滚。
- Windows 负责平台无关单元/fixture；Harbor、官方 Harness 与真实 DeepEval/Opik 必须在 Linux 验收。
- 不实现批量、并发、调度器、CI gate、Web UI、插件系统或通用 checkpoint/resume。

## 总验收

- 一条固定 SWE-bench Verified instance 能从指定 commit 运行到官方 Harness 结果。
- 同一次运行产生 DeepEval 三项分析与可在 Opik Cloud 按 run_id 查看的脱敏 trace。
- 一个薄命令输出严格 JSON 和中文 Markdown，且任一 Judge/Cloud 故障不改写正式得分。
