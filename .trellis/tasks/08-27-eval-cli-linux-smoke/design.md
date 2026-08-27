# 设计：薄组合入口

## 最小链路

verified-run 参数 → run_verified_evaluation → 已有 artifact/Harbor/Harness/DeepEval/Opik 模块 →
VerifiedEvaluationReport → JSON 与中文 Markdown。

## 边界

- Python 函数是唯一组合逻辑；CLI 和 DeepEval pytest 入口都只调用它或其已完成阶段。
- 每层接收上一层 typed 结果，不通过 stdout 或临时约定字段拼装。
- 一个 run 对应一个 instance 和一个输出目录；不引入数据库、队列或调度器。
- 保留四段独立状态，退出码只表达整体 completed/subject/infra/invalid。
- 复用现有报告模型和写入方式，仅增加 Verified 展示，不建立第二套报告框架。

## 失败与回滚

- 下游 DeepEval/Opik 失败仍写入包含官方结果的报告。
- Harbor/Harness infra 失败时停止依赖它们的下游阶段并输出明确状态。
- 回滚本任务后，三个底层模块仍可由 Python API 独立运行。
