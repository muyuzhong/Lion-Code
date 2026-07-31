# 构建编码 Agent 端到端评测闭环

## Goal

为 Lion 建立可复现、可归因、可持续校准的编码 Agent 评测闭环。它用自建跨文件任务保障日常变更质量，用 SWE-bench-Live 外部锚点检验自建分数是否真的反映泛化能力，并把被验证的失败轨迹转化为新的回归样本。

## Approved Decisions

- 受测对象是 Lion 的当前生产 Agent 配置。每次运行从显式 profile 解析 model、provider、thinking、turn/cost 上限和工具策略，并把最终配置指纹写入实验清单；不在代码中固化某个 API Key、模型或供应商。
- V1 自建 30 题：跨文件重构、缺陷修复、特性开发各 10 题。其中 18 题为 regression split，12 题为 holdout split。自建题每题 3 次 rollout，以多数结果决定该题通过。
- V1 外部锚点为 20 条锁定的 SWE-bench-Live Python 实例。每条先执行 gold patch 三次，只有本机三次都有效的实例进入当次分母；首轮每题运行 1 次 Agent，方差或结论不稳定才扩展重复。
- 首次完整锁定运行得到真实基线 X。成功目标为：不降低外部锚点表现、无灾难性回退时，使自建 holdout 成功率达到 Y 大于等于 X 加 10 个百分点。若外部校准否定自建集的预测力，优先修正评测集，不以追逐 Y 代替校准。
- 在线运行必须由调用者显式传入正的预算上限和凭证环境变量；计划和结果都不保存密钥。实际预算不是实现阻塞项，而是每次付费执行的操作前置条件。

## Confirmed Constraints

- 现有 benchmarks/context_management 是 9 项仓库派生的上下文压缩 A/B/C 基准，已具备 JSON/中文报告、checkpoint、预算和质量护栏；它直接调用 OpenAI 兼容客户端，不执行完整 Lion Agent、隔离工作区、补丁验收或失败归因。
- Agent.run() 已提供 final text、stop reason、turns、耗时、token、缓存 token、近似成本和错误；Agent.core_runtime 可订阅 typed Core events。评测应使用这些边界，而非抓取 stdout 或把 JSONL session 当诊断日志。
- Agent 的 ToolContext 当前取进程 cwd。Agent 在 bypassPermissions 下允许 shell 和文件工具，因此 Git worktree 只解决污染，不能保护 hidden verifier 或 host 文件。
- Agent 已可接收独立 SessionRepository，因此评测 session 可以放到工作区之外，不污染待测 patch。
- 当前工作站有 Python 3.13 与 Git worktree，但 Docker daemon 未启动。Docker 缺失必须使正式端到端/外部锚点运行以可解释的 blocked 状态退出，不能产生成绩。

## Requirements

### R1. 任务集与防泄漏

- 每条自建题必须包含固定 base revision、Agent 可见的任务说明、任务分类、公开 setup、独立工作区规则、私有 verifier/gold 证据、涉及文件和难度标签。
- 入库前必须证明 base revision 失败、gold 修复通过，并记录环境、验收命令、耗时、稳定性和证据哈希。
- 被用于提示词、压缩策略或工具修复的题自动进入 regression split，永远不能同时作为无偏 holdout。失败回流也遵循相同规则。
- 外部锚点按版本、分层规则和 seed 在运行前冻结；不得看过候选结果后替换实例。

### R2. 可复现实验与隔离

- 每次运行生成不可变 experiment manifest，至少含 agent/runtime/evaluator code SHA、catalog SHA、profile 指纹、任务选择、seed、重复、超时、预算、平台、镜像和实际有效分母。
- 正式成绩只由容器化的 Agent workspace 与独立 verifier 产生。gold patch、hidden tests、宿主机结果目录和凭证不得挂载到 Agent 容器。
- 评测捕获受控轨迹、最终 patch、验收输出和结构化 AgentRunResult。提供商、镜像、Docker 和 verifier 故障必须单列为 invalid 或 blocked，而不是计为 Agent 失败。

### R3. 指标与外部有效性

- 主指标是 hidden verifier 通过的 task_resolved。辅助指标包括 patch apply、测试前后状态、耗时、轮次、token、缓存 token、费用、stop reason、重试和无效原因。
- 用至少五个预注册配置变体（基线、三类受控变更、一个有意劣化对照）同时评估自建 holdout 与外部锚点，比较排名相关性和提升/回退方向一致率。
- 校准阈值写入版本化 evaluation lock；V1 推荐 Spearman 相关系数不低于 0.70 且方向一致率不低于 80%。不足时，自建集只能用作诊断而不能单独构成合入门禁。

### R4. 回归门禁

- prompt、压缩、工具注册表、权限或执行策略变更必须声明其 profile 指纹，并对冻结 regression split 与批准基线进行同任务、同 seed、同资源限制的比较。
- V1 门禁通过条件是：有效分母一致；不存在关键任务从基线 3/3 成功到候选 0/3 成功的灾难性回退；配对成功率下界不低于 evaluation lock 中的非劣界。建议初始非劣界为负 10 个百分点。
- 结果状态必须区分 pass、reject、invalid 和 waived。累计拦截数只计 reject 且该候选未合入；invalid 和 waived 必须保留原因但不计为回退。

### R5. 失败归因与回流

- 首批 primary failure mode 为死循环、上下文腐烂、工具误用、过早终止；基础设施/提供商故障和待分类是隔离状态，不进入 Agent 失败率。
- 自动规则只能提出候选标签；入库前必须有轨迹、最终 diff、验收输出和可复现命令支持的人工/规则复核。
- 一条通过复现、去重、base/gold 校验与泄漏审查的失败，可以成为 regression 样本，或被隔离为未来 holdout；不能同时用于调优和无偏最终度量。

## Task Map

| Child task | Responsibility | Depends on | Completion evidence |
|---|---|---|---|
| 07-30-evaluation-foundation | 运行器、容器边界、数据契约、受控轨迹、报告骨架 | 无 | fake provider/假 Docker 的离线测试和契约校验 |
| 07-30-evaluation-task-corpus | 30 条自建任务、gold/base 稳定性与 split 防泄漏 | foundation 的 catalog 契约 | 每题 base 失败/gold 通过证据与 catalog 校验 |
| 07-30-evaluation-external-anchor | SWE-bench-Live 锁定抽样、gold 三次预检和外部校准 | foundation；Docker 可用时运行 | 可复跑 selection manifest、有效分母与校准报告 |
| 07-30-evaluation-regression-feedback | 配置比较门禁、拦截账本、失败 taxonomy 与样本回流 | foundation、task corpus；校准后启用强制门禁 | 判定测试、failure evidence 和至少一次安全回流 |

## Parent Acceptance Criteria

- [ ] 四个子任务分别产出可独立验证的实现和证据，并由父任务做一次端到端整合演练。
- [ ] 自建 catalog 具有 30 条合格题和冻结的 18/12 split；所有题都能证明 base 失败与 gold 通过。
- [ ] 外部锚点的 20 条实例、数据集版本、抽样 seed、gold 预检和实际有效分母均被记录；Docker 不可用时不会伪造结果。
- [ ] 报告能同时展示 N、X、Y、成本、重复次数、置信区间、配置指纹、无效项和外部有效性结论。
- [ ] prompt、压缩与工具变更可以经过同一 gate；reject 有可审计记录，且不会将运行基础设施错误误计为回退。
- [ ] 四类 Agent 失败模式可复现、可归因、可回流，并有 split 防泄漏测试。

## Out of Scope

- 为迎合基准修改 Lion 的业务行为，或将评测诊断写入用户 JSONL session。
- V1 支持所有 SWE-bench-Live 语言、Windows 容器、分布式调度、自动训练或自动合并候选。
- 将单轮小样本结果宣传为生产成功率或统计显著收益。

## Risks and Deferred Items

- Docker daemon 当前不可用；基础代码可用 mock/离线校验完成，但正式自建隔离运行与 SWE-bench-Live 校准必须在 Docker 可用的机器执行。
- API 成本和模型波动通过显式 budget、checkpoint、有效分母和版本化 manifest 控制；没有运行凭证与预算时，在线命令必须拒绝启动。
- 30 条高质量任务需要独立 curate，而不能从提交 diff 自动批量生成。自动抽题仅可辅助发现候选，不能替代 base/gold/泄漏审查。
