# 编码 Agent 端到端评测闭环设计

## 设计目标与不变量

1. 可执行 verifier 才能定义成功；模型自述、git diff 非空或测试命令退出码单独都不足以判定任务成功。
2. 被测 Agent 不能读取 gold patch、hidden tests、宿主机结果或上轮任务状态。Git worktree 不是安全边界，因为当前 bypassPermissions 允许任意 shell。
3. prompt、压缩和工具策略是受控实验变量，必须与任务、模型、资源上限一起冻结。
4. Docker/镜像/提供商故障与 Agent 解题失败是不同事件，分母和报告必须保持这一差别。
5. 评测在 Lion 既有 Agent/Core/Tool 边界外编排，复用 Agent.run、Core events 和独立 SessionRepository；不得引入 stdout 协议或改写用户 session。

## 系统边界

新代码放在 benchmarks/agent_e2e，测试放在 tests/benchmarks。该目录是评测 harness，不属于 lion_code 的生产运行时。

正式运行由三个隔离层组成：

- Host orchestrator：读取锁定 catalog/profile，创建临时工作区，控制预算/checkpoint，启动容器并写入结果。它持有 hidden verifier、gold patch 和最终报告。
- Agent container：仅得到 base workspace、面向 Agent 的 issue、当前候选 Lion runtime 和临时 API 凭证；在 workspace 内运行完整根 Agent，产出修改后的工作区和受控 trace。
- Verifier container：在 Agent 退出后，独立加载 base workspace 加 patch 与 hidden verifier；只有它给出 task_resolved。它不向 Agent 返回 hidden test 内容。

容器边界不可用时，运行器可以进行 catalog、patch 格式、manifest 和 fake provider 的离线验证；它不得生成 official task_resolved、X、Y 或外部校准结论。

## 目录与模块边界

- benchmarks/agent_e2e/models.py：不可变 manifest、task、profile、result、verdict、failure record 模型与 JSON 序列化。
- benchmarks/agent_e2e/catalog.py：读取 catalog、冻结选择、split 和 base/gold 校验。
- benchmarks/agent_e2e/orchestrator.py：checkpoint、预算、worktree/container 生命周期和批量排序。
- benchmarks/agent_e2e/agent_worker.py：容器内构造 Agent、订阅 Core events、运行单题并输出无密钥的 worker result。
- benchmarks/agent_e2e/verifier.py：patch 获取、私有验收调用和判定规范化。
- benchmarks/agent_e2e/trace.py：事件精简、内容脱敏、循环指纹和失败候选标签。
- benchmarks/agent_e2e/report.py：JSON、中文 Markdown、置信区间、校准和 gate 报告。
- benchmarks/agent_e2e/gate.py：基线/候选配对比较、判定状态和拦截账本。
- benchmarks/agent_e2e/data：公开任务描述、catalog 和选择 manifest；私有 verifier/gold assets 不进入 Agent 容器，也不放入 Agent 工作区。

在线输出放在被 gitignore 的 benchmarks/agent_e2e/results；冻结 catalog、lock、公开题目和测试夹具应提交到仓库。

## 数据契约

TaskSpec 至少包含 task_id、family、split、target repository/base revision、issue 摘要、公开 setup、公开允许的验证命令、verifier identity、gold evidence hash、难度、涉及文件、预估资源和状态。私有 verifier 的真实路径只存在于 Host 的私有任务注册表，不能写入 Agent 可见 TaskSpec。

ExperimentManifest 至少包含 schema version、run_id、created_at、agent code SHA、evaluator code SHA、catalog SHA、profile fingerprint、model/provider 名称、thinking、permission/tool policy、prompt/compression/tool version、task IDs、seed、repeat、timeout、budget、platform、image digest 和恢复父 run。密钥只记录环境变量名称，绝不记录值。

TaskResult 至少包含 task_id、attempt、verdict、validity、patch SHA、apply 状态、验收命令摘要与退出状态、AgentRunResult 字段、受控 trace 路径、开始/结束时间、成本记账与 invalid reason。正式聚合前必须保证每个 result 与 manifest 的任务、profile、运行时版本匹配。

FailureRecord 至少包含 task result 引用、一个 primary mode、可选 secondary modes、evidence offsets、failure signature、root-cause 结论、复现命令、triage owner、去重状态、回流 split 和禁止作为 holdout 的理由。

## Agent 执行适配

容器内 worker 以 workspace 为 cwd 构造 Agent，并传入 terminal_output=False、独立 SessionRepository、显式 model/provider/limits 和自动确认函数。worker 订阅 agent.core_runtime 的 typed events，完成后取消订阅并始终调用 agent.close。

为保持完整根 Agent 行为又避免机器级 MCP 污染，foundation 将增加一个窄的 Agent 构造参数 mcp_enabled，默认 True。评测 worker 固定 False；这只能跳过 MCP 发现，不能更改既有默认 CLI/TUI 行为。对应测试证明默认仍发现 MCP，而评测 profile 不发起 MCP 连接。

评测的 permission_mode 可以是 bypassPermissions，因为容器才是安全边界；host/process fallback 不可使用它产生官方成绩。Agent 的 SessionRepository 指向容器内临时目录，避免 JSONL entry 出现在被测 git diff。

profile 不从私有 Agent 字段反射 prompt 文本。profile 显式提供 prompt_version、compression_version 和 tool_policy_version，并同时记录 agent code SHA；这些字段与变更分类共同构成可审计的配置指纹。

## 任务与验收流程

自建任务以候选 Lion runtime 和历史 target workspace 分离运行：候选 Lion 源码位于 Agent image，任务工作区则检出到任务的 base revision。这样即使任务目标也是 Lion，Agent 本体不会因编辑工作区而改变自身 runtime。

每次尝试的顺序为：

1. Host 验证 catalog/lock、剩余预算、Docker 和 base revision。
2. Host 创建干净 detached worktree 或等价的只含公开任务资产的工作区。
3. Agent container 在该工作区执行一次完整 Agent.run，输出 trace 与最终 diff。
4. Host 计算规范化 git diff HEAD 并以 SHA 固化；无 patch 不等于失败，仍由 verifier 判定。
5. 新 verifier container 应用 patch 并运行 hidden acceptance；Agent 已无法再观察该容器。
6. Host 写入单题 checkpoint，刷新 aggregate/report，并在异常时保留可恢复的未归属费用。

自建题准入顺序是 base verifier fail、gold patch apply、gold verifier pass、重复稳定性检查、公开/私有资产泄漏检查、split 分配。任何一步失败都不能进入报告分母。

外部锚点采用相同 TaskResult 契约。SWE-bench-Live 选择 manifest 固定数据集 revision、split、seed、筛选规则、平台和 20 个 instance ID。每个 instance 的 gold patch 先跑三次；三次有效才进入该次 anchor denominator。官方外部 patch 评估器是 verifier 的唯一真源。

## 统计、校准与门禁

单题自建结论是三次 rollout 的多数通过；外部首轮为一次，但报告必须显式标记重复次数和不确定性。所有百分比给出成功数、有效分母和 Wilson 或 bootstrap 区间；不能只显示百分比。

校准先冻结五个 profile，再收集 self holdout 与 anchor 的 profile-level 分数。报告 Spearman 排名相关性、每个候选相对基线的符号一致性、置信区间和分歧案例。V1 的推荐通过阈值为相关系数至少 0.70、方向一致率至少 80%，最终阈值保存在 evaluation lock，而不散落在报告代码。

gate 输入是批准 baseline manifest 与 candidate manifest。比较仅接受相同 catalog、task selection、profile 资源上限和有效分母。若结果不可比则 invalid；若关键任务从基线 3/3 到候选 0/3，或配对下界低于非劣界则 reject；人工 waiver 需要原因/批准人，独立于 reject。只有 reject 且候选未合入写入 interception ledger。

## 失败 taxonomy

- 死循环：同一工具和参数摘要或无进展 workspace diff 指纹连续重复至少三次，且达到 timeout/max turns/budget。
- 上下文腐烂：轨迹证据表明已读的关键约束被后续行为遗忘、矛盾或被压缩后不可恢复；自动检测只标候选，最终由 evidence review 确认。
- 工具误用：无效参数、越界路径、权限/工具错误后重复同类调用，或工具能力与任务步骤明显不匹配。
- 过早终止：Agent 报 completed 或主动结束，但没有完成必要验证、没有足够 patch，且 hidden verifier 失败。
- 基础设施/提供商故障：Docker、镜像、网络、认证或 verifier 自身失败。它们产生 invalid/blocked，不进入 Agent failure rate。

回流要先基于 task/profile/trace 生成稳定 failure signature，再人工确认复现、去重、base/gold 和泄漏状态。用于修复的失败进入 regression；保留为未来 holdout 的失败必须在任何调优前冻结。

## 兼容性、隐私与回滚

默认 Agent CLI/TUI、MCP、JSONL session 和已有 context benchmark 行为保持不变。mcp_enabled 默认为 True；评测 session 只写临时目录；trace 对工具参数、环境和输出执行密钥/路径脱敏，并保留摘要/哈希而非大段敏感内容。

评测文件可独立移除，不迁移用户数据。若新 Agent 构造参数或观察器出现回归，回滚该窄 seam 即可，已有 Agent 默认路径不受影响。在线结果从不提交；可提交的只有 manifest、公开 catalog、统计摘要和无敏感的失败分类。
