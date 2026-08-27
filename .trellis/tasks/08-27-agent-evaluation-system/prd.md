# 构建 Lion 自动化评测系统

## Goal

在 Linux Docker 服务器上建立一条可复跑的 Lion 单题评测链路：从当前 Git commit 构建 Lion，
使用 Harbor 运行一条 SWE-bench Verified 官方任务，以确定性 verifier 判定任务完成度，再由
DeepEval 对同一次运行的受控轨迹做离线 LLM Judge 分析，并把同一条脱敏轨迹上传到 Opik Cloud
进行树状可视化。该链路用于比较 Lion 工具、提示、上下文管理等模块改动前后的效果，不让 LLM
Judge 或云端可观测性覆盖官方正确性得分。

## Requirements

- 复用现有 `benchmarks/agent_e2e/` 的版本化模型、报告、轨迹脱敏和外部锚点约束，不建立平行的
  `evals/` 框架，也不为评测复制 Agent、Provider、Session 或工具执行路径。
- MVP 只支持一次运行一个 SWE-bench Verified instance；任务 ID、模型、预算、超时等保留为显式
  参数，批量、并发、定时和 CI 门禁后置。
- 运行对象必须是一个已提交的 Git commit。构建上下文来自该 commit，不读取或打包工作区未提交
  内容；manifest 记录 commit SHA、依赖版本、任务 ID、模型配置和环境指纹。
- Harbor 负责官方任务环境、Lion 安装、Agent 生命周期、常规 verifier、job 目录和 Viewer；Lion
  通过 Harbor 的标准 installed-agent 扩展运行，不依赖桌面端。
- Agent 在一次性任务容器中以 bypass permission 执行。准备阶段允许获取固定依赖；Agent 阶段只
  允许访问模型 Provider 白名单，不开放通用互联网。服务器网络策略的落地方式写入部署文档，
  不在本任务中 provision 服务器。
- Harbor verifier 提供日常确定性验收；同一 patch 还必须导出为官方 SWE-bench prediction JSONL，
  并由官方 SWE-bench Harness 完成正式可比的复核。只有官方 Harness 结果可写入现有
  `TaskResult.official=true`。
- DeepEval 在 Agent 退出后运行真实的离线 LLM Judge，分析目标推进、工具选择、重复/卡死、提前
  终止和失败原因；它只生成过程分析，不能改变 verifier 的 passed/failed。
- DeepEval 的评测逻辑使用 Python SDK 写入 benchmark 层：trace 接入、metrics 和 typed result 都是
  可测试代码；同时提交一个最小 pytest eval suite，并以 `deepeval test run` 作为标准 DeepEval
  运行入口。项目 `verified-run` 命令只复用同一个 Python API，不能形成第二套评测逻辑。
- 首版使用 3 个高信号指标：`TaskCompletionMetric`、`StepEfficiencyMetric` 和一个覆盖计划、工具、
  重复/提前终止及失败归因的自定义 `GEval`。其中任务完成指标仍是诊断信号，不能覆盖官方 Harness。
- Judge 输入可短暂使用经过 secret redaction 的消息、工具参数与结果，但不保留隐藏推理；持久化
  结果继续遵守现有更严格契约：只保存受控摘要、digest、评分和原因，不保存原始 session、完整
  工具输出、凭证或私有 verifier 资产。Judge 完成后清理临时输入。
- Opik Cloud 是必须交付的 trace 可视化端。由于没有公开的 DeepEval→Opik 原生直连，Linux
  evaluation host 使用 Opik Python SDK，从与 DeepEval 同源的脱敏轨迹创建 agent/llm/tool trace
  tree，并把 DeepEval scores 写成 trace feedback；两端使用相同 `run_id`、task、commit 和 profile
  fingerprint 关联。
- Opik 凭证只存在于 Linux evaluation host，通过环境变量读取，不能进入 Harbor Agent 容器、
  manifest、trace payload 或报告。Opik 上传失败不能改变 Harness verdict 或 DeepEval score，只生成
  独立、可重试的 observability failure。
- Opik trace 固定在 Agent、Harness 与 DeepEval 全部结束后由 Linux 宿主批量发布，使最终 verifier
  与 Judge scores 进入同一 trace；MVP 不提供运行过程中的实时 Opik streaming。
- 区分执行状态与任务得分：`completed`、`subject_failed`、`infra_failed`、`indeterminate` 是运行
  状态；passed/failed 是 verifier 结果。基础设施失败不进入有效模型分母，并可按显式策略重试。
- 本地产物只写 Harbor 标准 job 目录及现有评测 JSON/中文 Markdown 报告；云端展示复用 Opik
  Cloud，不引入自建数据库、Confident AI Cloud 或额外 Web UI。
- Harbor、DeepEval、SWE-bench 相关依赖保持 benchmark-only 且固定版本，不能进入 `lion_code`
  生产导入图；除非现有公开接口确实不足，不修改产品 Runtime。

## Acceptance Criteria

- [ ] 一条命令可从干净的 Linux 主机环境选择一个 SWE-bench Verified instance，并以当前 commit
      构建/安装 Lion 后完成单题 Harbor trial。
- [ ] 运行 manifest 可证明 commit、任务、依赖、模型、预算、超时、镜像和网络策略；工作区未提交
      文件不会进入构建产物。
- [ ] Harbor job 中包含可审计的 Agent 结果、patch、常规 verifier reward 和受控 trajectory；Agent
      无法读取 verifier 私有资产或 verifier 输出。
- [ ] patch 可生成官方 SWE-bench prediction JSONL，官方 Harness 的 resolved 结果被归一到现有
      `TaskResult`/`EvaluationReport`，且与 Harbor reward 的一致/不一致都被显式报告。
- [ ] DeepEval 对同一运行产生真实 Judge 结果，记录 metric、score、reason、judge model 和输入
      digest；测试证明 Judge 无权改写官方 verdict。
- [ ] 同一次运行在 Opik Cloud 中可按 `run_id` 找到一棵 agent/tool/llm trace，能够关联 task、commit、
      profile、timing、状态、官方 verdict 和 DeepEval metric scores，且云端内容通过敏感信息检查。
- [ ] Opik 凭证不进入 Agent 容器或持久化产物；Cloud 发布失败/超时有独立状态和重试入口，不影响
      已完成的 Harbor、Harness 或 DeepEval 结果。
- [ ] 仓库包含独立 metrics 模块和一个 traced pytest eval suite；`deepeval test run` 与项目
      `verified-run` 调用同一 Python 评测 API，且不会重复执行同一条 Agent 任务。
- [ ] Agent 异常、超时、Harbor/Docker 故障、Harness 故障、Judge 故障和人工取消均有稳定分类；
      `infra_failed` 不计入有效分母，Judge 失败不抹掉已有确定性得分。
- [ ] 凭证、隐藏推理、完整 session、完整工具输出、私有测试和宿主绝对路径不出现在持久化报告；
      Judge 临时输入在成功和异常路径均被清理。
- [ ] 离线单元/集成测试不调用真实 Provider；在 Linux Docker 服务器完成一条真实单题 smoke，保留
      Harbor、官方 Harness 与 DeepEval 三段证据。
- [ ] 提供安装、Provider 环境变量、网络边界、运行命令、结果目录和故障处理文档；不要求新增 UI。
- [ ] Windows 本地可运行不依赖 Docker/Provider 的契约、解析和 fake 测试；Harbor adapter、官方
      Harness 和完整 smoke 必须在 Linux Docker 环境开发验证，不能以 Windows-only 结果验收。

## Out of Scope

- SWE-bench Verified 全量/批量运行、并发调度、定时任务、CI 自动门禁和 baseline/candidate 统计比较。
- 运行时在线 Goal Evaluator，或把 LLM Judge 反馈回当前 Agent 循环。
- Linux 服务器、Docker、出口代理、镜像仓库和密钥系统的自动化 provisioning。
- Confident AI Cloud、独立数据库、自建 Dashboard，以及对 Lion 桌面端的依赖；trace UI 只使用
  Opik Cloud。
- 实时 Opik streaming、宿主 relay 与 credential proxy；MVP 只做任务结束后的安全批量发布。
- 用 Harbor 替换现有自建任务集或 SWE-bench-Live 外部锚点；本任务只新增 Verified 单题纵向链路。

## Dependency

正式 smoke 依赖 Linux Docker、可用的模型 Provider 凭证、DeepEval Judge 凭证、Harbor/SWE-bench
镜像、Opik Cloud workspace/API key 与足够预算。缺少任一外部条件时，离线实现仍须可验证，但不得
虚构正式成绩或云端 trace。
