# 实施计划

1. 在 Linux 环境确认并固定 Harbor、SWE-bench Verified 和官方 Harness 的真实版本与公共入口。
2. 实现 commit artifact builder，并用 Windows 临时仓库测试 Git tree 导出、digest、脏工作区隔离和清理。
3. 实现最小 Harbor installed-agent 与单题 runner，复用 Agent.run、typed events 和现有 parser。
4. 将 patch 写为官方 prediction JSONL 并调用固定 Harness，归一到既有 TaskResult。
5. 覆盖无 patch、Agent 失败、超时、路径越界、schema 漂移、Harness 故障与 Harbor/Harness 分歧。
6. 在 Linux Docker 跑一条不含 DeepEval/Opik 的真实单题 smoke。

## 验证

- compileall、受影响 tests/benchmarks、git diff --check。
- 项目 Ruff、format、mypy 与质量基线；区分既有基线噪声。
- Linux smoke 记录 commit、instance、镜像/依赖 fingerprint、Harbor job 和 Harness 受控结果。

## 停止条件

- 固定版本无法形成 installed-agent + 官方 Harness 链路时停止，不自写调度器或 verifier。
- Agent 能访问私有资产、宿主 checkout 或 Docker socket 时停止正式运行。
