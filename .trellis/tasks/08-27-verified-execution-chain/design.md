# 设计：确定性 Verified 执行链

## 最小链路

Git commit → 临时源码树和 wheel → Harbor 单题 trial → patch 与 routine reward → 官方 Harness →
现有 VerifiedEvaluationReport。

## 边界

- 新逻辑只放在 benchmarks/agent_e2e；lion_code 不依赖 Harbor 或 SWE-bench。
- artifact builder 直接读取 Git object，不复制当前工作区；仅保留 SHA、wheel digest 和受控产物。
- Harbor 通过固定 executable 和 argv 调用，installed-agent 只复用现有 composition、Agent.run 与
  TraceRecorder，不新增第二套 Agent Runtime。
- SessionRepository 位于任务仓库外；Verifier、宿主 checkout 和 Docker socket 不挂载给 Agent。
- 官方 Harness 消费 Harbor 生成的同一 patch；Harbor reward 不提升为正式分数。
- 复用提交 425ef995 的 models 和 parser；不再增加另一组结果模型或通用 backend 抽象。

## 失败与回滚

- 版本/schema 漂移、Docker/镜像/通信错误为 infra_failed；无完整官方报告不进入分母。
- Agent 超时或报错但已有 patch 时仍允许官方复核。
- 每层先落盘受控结果，容器和 staging 在 finally 清理；失败不删除可诊断的非敏感摘要。
- 本任务是一笔独立提交，回滚不影响已冻结的结果契约。
