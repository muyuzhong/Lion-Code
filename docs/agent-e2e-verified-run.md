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

### 受限主目录与缓存重定向

评测主机主目录只读或受限时，跑通依赖两项重定向（一键脚本
`scripts/benchmarks/verified-smoke/run_smoke.sh` 会自动执行，以下为
原理与手动等价做法）：

- `HOME` 重定向：Harbor 硬编码 `~/.cache/harbor`，必须把 `HOME` 指向
  可写目录（如 `export HOME=/path/to/harbor-home` 并提前
  `mkdir -p "$HOME"`）。
- `HF_HOME`/`XDG_CACHE_HOME` 重定向：官方 Harness 装载数据集时按
  passwd 主目录（而非 `$HOME`）解析缓存，受限主目录下会复现
  `PermissionError: /home/<user>/.cache/huggingface`；显式指到可写区即可：
  `export HF_HOME=/path/to/hf-home` 与 `export XDG_CACHE_HOME=/path/to/xdg-cache`。

### DeepEval judge 端点

DeepEval judge 经 litellm 访问自定义 OpenAI-compatible 端点：设置
`export LITELLM_API_BASE=<endpoint>`（与 `OPENAI_BASE_URL` 同源；一键
脚本在未显式设置时自动取 `OPENAI_BASE_URL` 的值）；不设置时走官方端点。

### judge 独立配置与指纹

judge 模型与 agent 模型解耦：直接 CLI 可传 `--deepeval-judge-model`
显式指定（未传时默认跟随 `profile.model`，属显式可见的旧行为）；一键
脚本要求 `DEEPEVAL_JUDGE_MODEL` 必填并显式传递，避免 agent 模型换代
静默改变评分基准。`DeepEvalAnalysis` 同时记录 `agent_model`、
`judge_model` 与 `judge_fingerprint`（SHA-256 于 judge 模型 +
`LITELLM_API_BASE`，端点只进哈希不进报告原文）——换机或换代后可按
指纹追溯评分基准是否一致。

### 评分阈值与独立指标语义

两项诊断统一阈值 0.5（运行侧策略常量，≥0.5 视为达阈值）：
`DeepEvalMetricResult` 记录 `threshold`/`threshold_met` 逐项对照，
并保留每项指标的 score、reason、status、采样范围和模型/输入 digest。
DeepEval 不计算或持久化跨指标的 aggregate pass/fail 结论；报告逐项展示
这些观测字段。官方 Harness verdict 仍是唯一权威的确定性判定，judge
分数与 Harbor reward 一样不参与 `task_result` 判定，也不影响 CLI 退出码
约定。

DeepEval 只消费 worker 产生并经 schema/digest 校验的
`analysis-trace.json`，输出 `ArgumentCorrectnessMetric` 与
`ToolDecisionQuality`。旧 `trajectory` 仍用于既有过程/Opik 观测；旧运行
缺少 Analysis Trace 时，DeepEval 记为 unavailable，不从 digest 逆构造参数。
Analysis Trace 是 DeepEval 的旁路 artifact：采集、构造、digest 校验或写盘
失败时只省略 `analysis-trace.json`（部分写入也会清理），不改变
`worker-result.json`、`trace.json`、patch、Harbor 或官方 Harness 结果；随后
DeepEval 按缺失 artifact 记为 unavailable。
Judge reason 已有 `[seq=N]` 时原样保留；未提供 sequence 时只附加
“（Judge 未提供 sequence 定位）”，不从第一条 Analysis Trace 事件补写序列。

### Harbor 与官方结果分歧

Harbor 例行 verifier 与官方 Harness 结论冲突时（如 verifier 因内部
环境失败给 reward 0.0 而官方 `resolved=true`），Markdown 报告在官方
Harness 段渲染"分歧标注"文字，明确失败归属：判定以官方 Harness 为准，
Harbor 侧仅过程证据。JSON 报告保留两段原始字段，分歧可由
`harbor.verifier_outcome`/`harbor.reward` 与 `harness.resolved`
推导；reward 仍不参与判定。

### judge 多次采样与均值±范围

每个指标默认独立采样 3 次（`--deepeval-samples` 可调；一键脚本对应
可选 env `DEEPEVAL_SAMPLES`），`score` 取成功采样均值，指标行同时
给出采样次数与范围 `score_min–score_max`；部分采样失败在 reason 中
标注"N 次采样失败"，全部失败仍沿用单次失败语义。采样在分析
deadline（`--deepeval-timeout`，默认 600 秒）内逐样本计时，超时样本
按 TIMEOUT 计入；模型延迟高时 deadline 需随采样次数放大（实测单次
judge 调用约 28 秒，3 次采样 × 2 指标的一轮约 170 秒；
ToolDecisionQuality 的 GEval 步骤可能更长，默认 600 秒为两轮留出余量）。
多次采样不保证
同一 payload 输出完全一致（LLM 无 stable seed），但给出均值±范围，
使漂移可见、可复核。

### 运行残留清理

`scripts/benchmarks/verified-smoke/cleanup_smoke.sh` 一键清理可重建的
运行残留（仅本机运维，不入 CI）：

- 默认删除缓存目录 `harbor-home/`、`hf-home/`、`xdg-cache/`
  （`run-*` 证据目录永不删除）；`SMOKE_CLEAN_DRY_RUN=1` 干跑只打印
  将删除项；`SMOKE_CLEAN_IMAGES=1` 时同时删除 `swebench/sweb.eval*`
  镜像（docker 删除失败仅警告）。
- 路径守卫：结果根指向被越界时拒绝执行（退出码 2）。
- 删除后缓存可重建，评测可无损重跑。

### digest 寻迹（digest → 脱敏摘要）

报告与 trajectory 中的 `payload_digest`/`trajectory_digest` 可经本地
寻迹账本反查：`verified-run` 设置 `--digest-ledger <path>`（一键脚本
默认 `$RESULT_ROOT/digest-ledger.jsonl`）后，每次运行把 input/trace
digest 与每个投影事件的 payload/argument digest 追加写入账本——只存
脱敏摘要与元数据（task/run/event_type/tool_name/时间），不存原始
正文，不破坏脱敏红线（results/ 整体 gitignore，不入库）。

```bash
python -m benchmarks.agent_e2e digest-lookup --ledger <ledger-path> <sha256...>
```

退出码：`0` 全部找到；`1` 存在未找到（仍输出已找到部分）；`2` 账本
缺失/不可读。

### smoke.env 权限

评测凭证文件 `smoke.env` 必须为 600 且属主为运行用户（
`chmod 600 smoke.env`）；一键脚本启动时自动强制该权限并校验属主，
无法保证时拒绝启动（退出码 2）。

DeepEval 离线分析显式关停上报：不要设置 `CONFIDENT_API_KEY`（设置了会
被分析入口拒绝并记录失败）；未设置时分析结果记
`extensions.telemetry == "off"`。DeepEval SDK 收尾阶段打印的
`deepeval view` / Confident AI 共享建议与 `All metrics errored ...
Posting the run anyway ... Confident AI dashboard` 横幅均为 SDK 固定
展示层文案（无官方开关）：横幅在 SDK 的 TestRun 未收集到 metric data
时必然打印，即使两项诊断实际已 completed 且带分数——属于已知输出，
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
legacy trajectory、`analysis-trace.json`、DeepEval 和 Opik payload 引用。JSON 可用
`VerifiedEvaluationReport.model_validate_json(...)` 重新校验；Opik trace 通过
同一个 `run_id` 定位。

退出码约定：`0` 为流程完成且官方结果通过，`1` 为被测 subject 失败，`2` 为
基础设施/依赖阻塞，`3` 为输入或结果无效。官方 Harness 已完成但判定未
resolve 时仍是 subject 失败，不会被当作基础设施错误。
