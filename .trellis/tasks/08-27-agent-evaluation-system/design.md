# Lion 自动化评测系统设计

## 1. 设计结论

采用现有方案的组合，而不是重写调度器：

1. **Harbor** 是 SWE-bench Verified 单题执行器，拥有任务镜像、installed agent、trial、常规
   verifier、job 目录和 Viewer。
2. **SWE-bench Harness** 是正式可比的确定性复核器，消费 Lion 产生的 patch。
3. **DeepEval** 是运行后的过程分析器，只消费受控轨迹，不参与任务正确性裁决。
4. **`benchmarks/agent_e2e`** 继续拥有 Lion 侧 manifest、严格结果模型、脱敏、报告和失败归类。

这条链路属于现有 external benchmark adapter，而不是现有 `ContainerBackend` 的具体实现。
`ContainerBackend` 要求 host 分别调用 `run_agent()` 和 `run_verifier()`，Harbor trial 则原子地拥有
两者及其容器生命周期。强行适配会引入跨调用缓存和双重编排，因此 MVP 参照已有
`external_anchor.py` 增加独立 Verified adapter，并把正式结果归一回同一个 `TaskResult`。

## 2. 固定链路

```text
current Git commit
  -> reproducible wheel + evaluation manifest
  -> Harbor SWE-bench Verified task + Lion installed agent
  -> patch + Harbor reward + controlled trajectory
  -> official SWE-bench Harness recheck
  -> DeepEval offline trajectory judge
  -> existing TaskResult / EvaluationReport + Chinese report
```

正确性优先级固定为：官方 Harness > Harbor 日常 reward > DeepEval 分析。若前两者不一致，结果
进入显式 verifier disagreement，不能由 DeepEval 仲裁。

## 3. 模块边界

### 3.1 Commit 构建与 manifest

新增 benchmark-only 的 commit artifact builder：

- 校验目标 SHA 可解析且已提交；从 Git object/tree 导出临时源码树并构建 wheel，绝不直接从脏
  工作区构建。
- 记录 wheel SHA-256、Git SHA、Python/平台、Harbor/DeepEval/SWE-bench 固定版本、任务 instance、
  Agent/Judge 模型、预算、超时、镜像 digest 和网络策略 fingerprint。
- 临时源码树与 wheel staging 在所有终止路径清理；最终 job 只保留 wheel digest，不复制源码。

现有 `ExperimentManifest` 仍是比较锁。Verified 专用但非敏感的 provenance 放在显式 typed model
或 `extensions` 中，不新增第二套 profile/manifest。

### 3.2 Harbor Verified adapter

新增 `benchmarks/agent_e2e/swebench_verified.py`，职责为：

- 验证 Harbor 数据集/instance 和固定依赖版本；构造单题 trial，不自行复制 SWE-bench task image、
  setup 或 verifier。
- 使用 Harbor 公共 `BaseInstalledAgent` 扩展把当前 commit wheel 与小型 adapter 上传到 task
  environment。adapter 在目标仓库 cwd 调用现有 `build_full_agent_harness` / `Agent.run()`，订阅 typed
  Core events，并在 finally 中关闭 Agent。
- 通过现有 `TraceRecorder` 生成持久化受控摘要；同时为 DeepEval 生成 job-private、secret-redacted、
  bounded 的临时 judge input。临时输入不含 hidden reasoning、凭证、完整私有测试或宿主路径。
- 从目标仓库导出 `git diff` patch，计算 SHA-256；不把 SessionRepository 放入目标工作区。
- 解析 Harbor `result.json`、reward、agent status、timing 和 artifact 路径，拒绝未知 schema、缺失
  patch 或脱离 job root 的路径。

Harbor 是子进程/CLI 边界而不是 `lion_code` 依赖；命令参数使用 argv，不拼接 shell 字符串。
Harbor API/schema 漂移通过固定版本和解析 fixture 暴露。

### 3.3 确定性评分

评分分两级但只有一个正式结论：

- **Harbor reward**：用于快速单题反馈，保留 `0.0/1.0` 及 verifier 摘要，标记为 routine。
- **官方 Harness**：将同一 patch 写成 `{instance_id, model_name_or_path, model_patch}` JSONL，调用
  官方 `swebench.harness.run_evaluation`。只有该结果可以构造 `official=true` 的 `TaskResult`。

若 Harbor 已失败但仍产生 patch，仍执行官方 Harness；若没有 patch、环境无效或 Harness 未完整
产出结果，则不得把该题计为 0 分，而是 blocked/invalid。报告同时显示两级结果及一致性。

### 3.4 DeepEval 离线分析

新增 `benchmarks/agent_e2e/deepeval_analysis.py`：

- DeepEval 是 benchmark-only 的 Python SDK 依赖。`deepeval_analysis.py` 拥有 trace/test case 转换和
  typed 结果；指标实例放在独立 `benchmarks/agent_e2e/deepeval_metrics.py`，不散落在 CLI 或测试中。
- 在 Harbor trial 与确定性 verifier 完成后运行，不订阅或干预在线 Agent 循环。
- 在 evaluation adapter 边界使用 DeepEval tracing API 包装 `Agent.run()` 并标注 agent/tool spans；
  事件内容继续来自 Lion typed events，不通过 stdout 解析，也不把 DeepEval 装饰器放入产品 Runtime。
- 首版只使用 3 个指标：`TaskCompletionMetric`、`StepEfficiencyMetric` 和自定义
  `GEval("TrajectoryQuality")`。GEval criteria 统一覆盖计划推进、工具选择、重复/卡死、提前终止和
  失败归因，避免一开始堆叠过多相互重叠的 Judge。
- Judge 返回 typed `metric/score/reason/model/input_digest`；整体状态和单项异常可序列化。
- 无论 Judge 成功、超时或抛错，都先保留确定性结果，再清理临时输入。Judge 失败只令 analysis
  unavailable，不把 task 改为 failed/invalid。
- 持久化报告不保存完整 Judge prompt/response，也不把 Judge reason 注入下一轮 Agent。

DeepEval 与模型客户端通过窄 protocol 注入；离线测试使用 fake judge，真实 smoke 使用显式 online
开关、预算和凭证环境变量名。

提交一个 `tests/benchmarks/evals/test_lion_swebench_verified.py` traced pytest suite。它读取已选择的
SWE-bench Verified task/profile，调用下面的共享 Python API，不重新实现 Harbor/Harness 逻辑：

```text
run_verified_evaluation(request) -> VerifiedEvaluationReport
```

DeepEval 标准入口为：

```text
deepeval test run tests/benchmarks/evals/test_lion_swebench_verified.py --identifier <run-id>
```

SWE-bench Verified 已是官方任务集，因此不调用 `deepeval generate`，也不生成一套平行 goldens；
adapter 只把选中的官方 task 投影为 DeepEval `Golden` 所需的 input/metadata。

### 3.5 Opik Cloud trace 可视化

Opik 是可观测性输出，不是第二个评分器。`@track` 支持 async 与嵌套 span，但实际 Agent 运行在
Harbor task container：若在容器内直接上传，具备 shell 权限的被测 Agent 可以接触 Opik 凭证。
因此 MVP 使用 Opik Python SDK 的显式 `Opik.trace()` / `Trace.span()` API 在宿主侧发布已完成的轨迹，
不导入 DeepEval 私有 exporter，也不把 Opik metrics 混入正式得分：

1. evaluation adapter 从 Lion typed events 构造一次有界、脱敏的临时 trajectory；DeepEval Python
   SDK 和 Opik publisher 都消费这份同源数据。
2. DeepEval 完成评分后，宿主创建 root agent trace，并按原始 start/end timestamp、parent ID 重建
   plan/llm/tool/error child spans。Opik SDK 负责 Cloud transport 和 UI trace tree。
3. root span 记录 `run_id`、task ID、attempt、commit SHA、profile fingerprint、patch SHA、执行状态、
   Harness verdict 和 DeepEval metric scores；child span 只记录受控名称、时长、状态和 bounded/redacted
   input/output summary，不记录 hidden reasoning、凭证、完整工具输出或私有 verifier 内容。
4. DeepEval 每个 metric 的 name/value/reason 写入 Opik trace feedback scores；正式 Harness verdict
   同时作为 metadata 与单独 feedback 展示，但 Opik feedback 不反向修改本地结果。
5. Opik 配置只从宿主环境读取：`OPIK_API_KEY`、`OPIK_WORKSPACE`、project name；manifest 只记录
   非敏感 workspace/project 名称和 export policy fingerprint。
6. 短命评测进程在 publisher 外层调用 `opik.flush_tracker()`；强制 flush 后记录 `trace_id` 与 export
   状态。上传失败是 `observability_failed`，可对已落盘的脱敏 trajectory 单独重试，不能重跑 Agent，
   也不能修改 deterministic/DeepEval 结果。

不使用 `track_openai`：该 integration 只支持 OpenAI/AsyncOpenAI client，而 Lion 当前
`OpenAICompatibleProvider` 与 `AnthropicProvider` 都直接使用 `httpx.AsyncClient`。LLM span 的 model、
provider、token usage、cost 与 timing 从 Lion typed events/usage 结果填充。也不把 `@track` 装饰器
写入 `lion_code` 产品路径；将来若需要实时 trace，另行设计不向容器泄密的宿主 relay。

MVP 固定使用后置批量发布：它隔离 Opik 密钥，并在 root trace 中带上最终 verifier/Judge 结果。
实时 streaming 需要宿主 relay/credential proxy，明确留到后续任务。

### 3.6 状态与结果

运行状态与任务得分正交：

| 执行状态 | 含义 | 是否进入有效模型分母 |
| --- | --- | --- |
| `completed` | Agent 生命周期结束且官方 Harness 得到有效 pass/fail | 是 |
| `subject_failed` | Agent 报错、超时或预算耗尽；若已有 patch 仍保留 verifier 结果 | 仅官方结果有效时 |
| `infra_failed` | Harbor、Docker、镜像、Harness、通信等基础设施失败 | 否，可重试 |
| `indeterminate` | 人工取消或清理未完成，无法可靠归因 | 否 |

现有 `TaskVerdict`/`ResultValidity` 继续表达 passed/failed/blocked/invalid；新增的执行状态只作为一次
trial 的生命周期事实，不能取代或复制 verdict。

## 4. CLI 与产物

Python API 是唯一组合逻辑。对外提供两个薄入口：DeepEval CLI 用于标准可复跑 eval，现有项目 CLI
用于运维、调试和无 pytest 的单题执行。MVP 项目命令例如：

```text
python -m benchmarks.agent_e2e verified-run --task-id <instance> --profile <json> --output <dir>
```

两个入口都复用同一组 Python 组合函数，按顺序执行 commit build、Harbor、official recheck、
DeepEval 和 report；一次只运行一个 instance，并使用显式 run-id。一个入口不得再通过 subprocess
调用另一个入口。MVP 不设计通用 checkpoint/resume。输出放在 gitignored results/job root：

- 冻结 manifest 与依赖/环境 fingerprint；
- Harbor job/result 引用、routine reward、patch digest；
- official prediction JSONL 与受控 Harness 结果；
- DeepEval typed analysis；
- Opik export status、trace ID 与非敏感 project reference；
- 统一 JSON 与中文 Markdown 报告。

不复制 Harbor Viewer；报告提供对应 job 目录的打开说明。

## 5. 安全与隔离

- Agent 容器允许 bypass permission，因为它是一次性 SWE-bench task sandbox；宿主 checkout、Docker
  socket、verifier 私有资产和 Judge 凭证不可挂载给 Agent。
- Provider 密钥仅从显式环境变量注入，模型调用出口经部署侧 allowlist/proxy；准备阶段和 Agent 阶段
  使用不同网络策略并写入 fingerprint。
- Opik Cloud 出口只开放给 Linux evaluation host 的后置 publish 阶段，Opik API key 不进入 Harbor
  environment；SDK 配置与错误日志不得打印 credential。
- 路径、JSON、trajectory 和工具参数均经过现有 redaction；秘密 key 检测和最大长度限制前置于落盘。
- Judge 临时输入位于当前 job 私有目录，成功、失败、取消都删除；报告只保留 digest 和受控结论。
- 所有外部命令用固定 executable + argv + timeout；不执行任务内容提供的 host shell 片段。

## 6. 依赖与兼容性

- 增加独立 benchmark-online 可选依赖，精确固定 Harbor、DeepEval、SWE-bench、Opik Python SDK
  版本；生产安装与 `lion_code` import graph 不受影响。
- 不保留旧版 adapter fallback。检测到不支持的 Harbor/result schema 或依赖版本时直接 blocked。
- 不修改 Runtime 公开契约；若 installed agent 确实缺一个非交互入口，只增加最小公开 seam，并用
  默认行为回归测试证明桌面/CLI 路径不变。

## 7. 验证策略

- 模型契约：严格 schema、unknown field、provenance、status/verdict 正交和 official-only invariant。
- Commit 构建：脏工作区隔离、不可解析 SHA、wheel digest、临时目录清理。
- Harbor adapter：argv、fixture result parsing、path traversal、缺 patch、超时、agent error、infra error、
  cleanup 和 secret redaction。
- Harness：prediction JSONL、结果解析、Harbor/Harness disagreement、无效分母。
- DeepEval：3 个独立 metric、trace/span 映射、partial failure、不能覆盖 verdict、临时输入在所有
  路径清理；真实 eval 使用 `deepeval test run`，普通单元测试仍由项目测试门禁执行。
- Opik：fake client 覆盖 span tree、timestamp/parent、feedback、metadata、redaction、flush、timeout 与
  retry；Linux smoke 验证指定 Cloud project 中能按 `run_id` 找到 trace，且上传故障不改变本地评分。
- CLI/report：两个薄入口复用同一组合函数、单题选择、退出码、JSON/中文 Markdown、无敏感内容，
  并证明不会重复运行 Agent。
- 最终在 Linux Docker 服务器做一条真实 Verified smoke；本地/CI 默认只跑离线 fake/fixture 测试。

## 8. 开发环境

整体采用 **Linux-first、Windows 辅助**：

- Windows 当前 checkout 适合完成版本化模型、fixture parser、redaction、报告、fake judge、CLI 参数和
  文档，并运行不依赖 Docker/Provider 的快速回归。
- Harbor installed-agent、SWE-bench task image、官方 Harness、容器挂载/权限/网络、Linux wheel 安装
  和真实 DeepEval smoke 必须在 Linux Docker 环境开发验证。
- 若只能选择一个主要开发环境，选择 Linux。Windows 通过的测试不能代替 Linux 端到端验收。
- Linux 使用独立任务分支/worktree；运行对象仍由 manifest 指定 commit SHA，开发 checkout 与被测
  commit 不混用。两端通过正常 Git 提交同步，不复制未提交文件。

## 9. 后续扩展点

MVP 通过后，再基于同一 manifest/result 扩展批量、并发、baseline/candidate 对比、自动重试、定时运行
和 CI gate；这些扩展不能改变 deterministic verifier 与 offline Judge 的权责边界。
