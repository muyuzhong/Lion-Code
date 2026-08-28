# SWE-bench Verified 单题运行

`verified-run` 只接受一个冻结 manifest、一个 catalog task 和一个 Git commit，
按 `artifact → Harbor → 官方 SWE-bench Harness → DeepEval → Opik` 顺序运行。
Harbor reward 不是官方成绩；没有 Linux、Docker、凭证或固定依赖时只会留下
blocked/infra 证据，不会生成 0 分。

## Linux 准备

在评测服务器的仓库 checkout 中执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[benchmark-online]"
python -m pip install "harbor==0.22.0" "swebench==5.0.1"
```

确保 Docker daemon 可用，并允许访问模型提供商、Harbor 所需镜像以及 Opik
服务。凭证只通过环境变量注入，不要写入 manifest、命令行或结果目录：

```bash
export <MANIFEST_PROVIDER_ENV_VAR>=...
export OPIK_API_KEY=...
export OPIK_WORKSPACE=...
```

其中 `<MANIFEST_PROVIDER_ENV_VAR>` 必须替换为 manifest 的
`profile.credential_env_vars` 中声明的变量名；值不要提交到 Git。

DeepEval 离线分析显式关停上报：不要设置 `CONFIDENT_API_KEY`（设置了会
被分析入口拒绝并记录失败）；未设置时分析结果记
`extensions.telemetry == "off"`。DeepEval SDK 收尾阶段打印的
`deepeval view` / Confident AI 共享建议与 `All metrics errored ...
Posting the run anyway ... Confident AI dashboard` 横幅均为 SDK 固定
展示层文案（无官方开关）：横幅在 SDK 的 TestRun 未收集到 metric data
时必然打印，即使三指标实际已 completed 且带分数——属于已知输出，
不表示发生上报。

## 单题运行

commit 必须与 manifest 的 `agent_code_sha` 一致。`--run-id` 用于显式校验，
省略时直接使用 manifest 中的值：

```bash
python -m benchmarks.agent_e2e verified-run \
  --catalog benchmarks/agent_e2e/corpus_assets/public_catalog.v1.json \
  --manifest /path/to/frozen-manifest.json \
  --task-id <CATALOG_TASK_ID> \
  --commit <40_CHAR_COMMIT_SHA> \
  --run-id <MANIFEST_RUN_ID> \
  --repository-root "$PWD" \
  --output-dir benchmarks/agent_e2e/results/<MANIFEST_RUN_ID> \
  --opik-project lion-agent-e2e
```

结果目录包含 `verified-report.json`、`verified-report.md`，以及受控的 patch、
trajectory、DeepEval 和 Opik payload 引用。JSON 可用
`VerifiedEvaluationReport.model_validate_json(...)` 重新校验；Opik trace 通过
同一个 `run_id` 定位。

退出码约定：`0` 为流程完成且官方结果通过，`1` 为被测 subject 失败，`2` 为
基础设施/依赖阻塞，`3` 为输入或结果无效。官方 Harness 已完成但判定未
resolve 时仍是 subject 失败，不会被当作基础设施错误。
