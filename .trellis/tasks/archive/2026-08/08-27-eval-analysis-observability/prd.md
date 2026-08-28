# 接入 DeepEval 与 Opik 离线分析

## Goal

对已完成的 Verified 运行做一次离线过程分析，并在 Opik Cloud 查看同源脱敏 trace；不得重跑 Agent
或改变官方 Harness 结论。

## Background

- 依赖 08-27-verified-execution-chain 产出的脱敏 trajectory、官方结果和 correlation metadata。
- 复用提交 425ef995 的 DeepEvalAnalysis、OpikExportResult 与 parser 契约。

## Requirements

1. DeepEval 固定三个指标：TaskCompletionMetric、StepEfficiencyMetric、TrajectoryQuality GEval。
2. DeepEval Python SDK 只存在于 benchmark 可选依赖和适配层，不进入 lion_code。
3. DeepEval 与 Opik 消费同一份 bounded/redacted trajectory，不保存 hidden reasoning、凭证和完整工具输出。
4. Opik 在 Linux 宿主后置发布 agent/llm/tool span tree，并附加 Harness 与 DeepEval feedback。
5. Opik API key 不进入 Harbor 容器；短命进程显式 flush，上传失败不影响评分且可基于既有轨迹重试。
6. Judge 超时或单指标失败时保留部分分析和完整确定性结果。

## Acceptance Criteria

- [ ] fake judge 覆盖三个指标、partial failure、timeout 和不能覆盖官方 verdict。
- [ ] fake Opik client 覆盖父子 span、时间、feedback、脱敏、flush 和独立 retry。
- [ ] DeepEval 标准 pytest 入口与项目组合逻辑复用同一分析函数，不会再次执行 Agent。
- [ ] Linux 真实 smoke 能在指定 Opik Cloud project 中按 run_id 找到 trace 和三项分析结果。
- [ ] DeepEval 或 Opik 不可用时报告 analysis/observability 状态，官方 Harness 结果保持不变。

## Out of Scope

- 在线 Goal Evaluator、实时 streaming/relay、track_openai、DeepEval 数据集生成、指标插件系统。
- 用 LLM Judge 判定任务 pass/fail，或把 Opik feedback 反向写入 Agent。

## Dependencies

- 必须等待 08-27-verified-execution-chain 完成并冻结真实 trajectory 产物。
- 08-27-eval-cli-linux-smoke 依赖本任务。
