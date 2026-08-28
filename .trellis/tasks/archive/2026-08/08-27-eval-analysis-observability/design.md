# 设计：同源离线分析与 Opik 发布

## 最小链路

已脱敏 trajectory + 官方结果 → DeepEval 三项指标 → Opik 后置 span/feedback → 更新
VerifiedEvaluationReport 的 deepeval/opik 字段。

## 边界

- 只新增固定指标构造和 SDK adapter，不设计通用 scorer registry。
- DeepEval 和 Opik 共用已冻结 trajectory；不得分别采集或重跑 Agent。
- Opik publisher 使用显式 trace/span API 重建树；Lion provider 基于 httpx，因此不使用 track_openai。
- 凭证只从宿主环境读取；report 仅保存非敏感 project、trace_id、状态和错误摘要。
- 正式 verdict 在进入本模块前已经冻结，所有异常只影响 deepeval/opik 字段。

## 失败与回滚

- 单项 Judge 失败保留其他指标；整体超时返回 typed unavailable/partial。
- Opik 失败保留可重试的脱敏轨迹引用，不重跑 Agent。
- 本任务可整笔回滚，确定性 Harbor/Harness 链仍可独立使用。
