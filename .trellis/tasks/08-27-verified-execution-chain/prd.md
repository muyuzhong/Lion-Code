# 接通 Harbor 与 SWE-bench 官方评分链

## Goal

让指定 Git commit 的 Lion 在 Linux Harbor 中完成一条 SWE-bench Verified 任务，并由官方
SWE-bench Harness 对同一 patch 给出唯一正式结论。

## Background

- 依赖提交 425ef995 已冻结的 Verified、Harbor 和 Harness 结果契约。
- 这是后续 DeepEval、Opik 和组合入口的上游任务；下游不得绕过本任务重新运行 Agent 或自行打分。

## Requirements

1. 从明确的 commit SHA 导出 Git tree、构建 wheel、计算摘要并清理临时目录；脏工作区内容不得进入产物。
2. 固定 Harbor、SWE-bench Verified 和官方 Harness 的实际可用版本；不保留旧 API fallback。
3. 通过 Harbor installed-agent 在任务仓库 cwd 调用现有 Lion Agent.run，保留脱敏轨迹与 patch。
4. Agent 看不到宿主 checkout、Docker socket、Verifier 私有资产和 Judge/Opik 凭证。
5. Harbor reward 仅作日常反馈；只有官方 Harness 可以产生 official TaskResult。
6. Agent、基础设施、取消和官方评分状态保持正交，失败路径也必须清理容器和临时目录。

## Acceptance Criteria

- [ ] Windows fixture/unit tests证明 commit 导出不包含未提交文件，digest 稳定且所有终止路径会清理。
- [ ] Linux Docker 中一条固定 Verified instance 能运行 Lion installed-agent 并导出 patch 或明确的被测对象失败。
- [ ] 同一 patch 被官方 Harness 复核，正式 pass/fail 或 infra/invalid 状态按已冻结契约序列化。
- [ ] 无 Docker、镜像、固定版本或官方报告时不会产生 0 分或伪造 official 结果。
- [ ] 日志和产物不包含凭证、原始 session、完整工具输出、宿主路径或私有 verifier 内容。

## Out of Scope

- DeepEval、Opik、批量/并发、CI gate、Web UI、通用 Docker 调度器。
- 自写 SWE-bench verifier、复制 Harbor Viewer、支持多个 Harbor/Harness 版本。

## Dependencies

- 上游：提交 425ef995。
- 下游：08-27-eval-analysis-observability、08-27-eval-cli-linux-smoke。
