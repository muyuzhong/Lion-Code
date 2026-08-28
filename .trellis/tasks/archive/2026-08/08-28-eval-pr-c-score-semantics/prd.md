# PRD:评测链 PR C(评分语义化)

> 来源:`benchmarks/agent_e2e/results/smoke-flask-5014/improvements-backlog.md`
> 推荐实施顺序第 3 项(P1-3 + P1-5)+ 第 4 项部分(P2-1)。
> 前序:PR A(#129,P0-1 + P1-1 + P1-2)与 PR B(#130,P0-2 + P0-3 + P0-4)
> 均已合并;本 PR 基于 master(`4abfea7`)。

## 1. 背景与目标

Verified 单题闭环(artifact → Harbor → 官方 Harness → DeepEval → Opik)
已能复现,但评分侧有三个语义缺口:

1. **P1-3 judge 独立配置**:CLI 未传 `--deepeval-judge-model` 时 judge
   默认跟随 `profile.model`(agent 模型)。agent 模型换代会静默改变评分
   基准,分数不可比;报告未同时记录 agent 模型与 judge 模型/指纹,
   无法区分"agent 是什么、judge 是什么"。
2. **P1-5 指标阈值与门禁语义**:三指标 `threshold=None`,分数纯观测;
   `deterministic_verdict`(官方 Harness 判定)已存在但未与 judge 分数
   合并展示。报告没有阈值对照,也没有门禁结论。
3. **P2-1 Harbor reward 与官方结果分歧标注**:正式运行中 Harbor 例行
   verifier 因内部环境失败给 reward 0.0,官方 Harness `resolved=true`
   (A5 报告 `run-flask-5014-20260828-161826` 即此场景),报告并列展示
   两块易误读,无失败归属文字。

目标:一个独立 PR,让"分数有意义"、judge 可独立固定与追溯、报告具备
明确的阈值对照、门禁结论与分歧归属;reward/judge 分数仍不参与判定
(不变量不变)。

## 2. 需求

### R1(P1-3)judge 独立配置与指纹

- R1.1 `DeepEvalAnalysis` 记录 `agent_model`(报告 manifest 的
  `profile.model`)与 `judge_model`(实际使用的 judge 模型),二者可不同,
  各自记录;另记录 `judge_fingerprint` = SHA-256(judge 模型 + judge
  端点),端点取运行环境 `LITELLM_API_BASE`(未设视为空)。
- R1.2 CLI `--deepeval-judge-model` 与默认跟随行为保持(直接跑 CLI 的
  用户可显式指定);一键脚本 `run_smoke.sh` 把 judge 模型收敛为必填
  `DEEPEVAL_JUDGE_MODEL`,显式传 `--deepeval-judge-model`,消除静默跟随。
- R1.3 报告(md/json)展示 Agent 模型与 Judge 模型及指纹。
- R1.4 验收:报告 judge 模型与 agent 模型各自记录且可不同;一键脚本
  缺 `DEEPEVAL_JUDGE_MODEL` 拒绝启动(rc=2)。

### R2(P1-5)指标阈值与门禁语义

- R2.1 三指标固定阈值常量(默认 0.5,含义:≥0.5 视为达阈值),构造
  DeepEval metric 时以阈值参数传入;`DeepEvalMetricResult` 记录
  `threshold` 与 `threshold_met`(completed 且有分数 → score ≥ threshold;
  其余 → False;无阈值记录时两者为 None)。
- R2.2 `DeepEvalAnalysis` 记录 `score_gate`:对已评分(completed)指标做
  阈值对照,`passed = 全部已评分指标达阈值`,`passed_metrics`/
  `evaluated_metrics` 计数,`reason` 受控短句;无已评分指标时 score_gate
  为 None(无法评估)。
- R2.3 报告 md 渲染"门禁结论":确定性判定(官方 Harness verdict)+
  judge 评分门禁对照,明确标注为观测、不参与判定。
- R2.4 CLI 退出码约定不变(score_gate 不改变 `verified_exit_code`);
  文档注明该不变量。
- R2.5 验收:报告(json/md)含阈值对照与门禁结论;同 payload 下
  score_gate 语义稳定、可断言。

### R3(P2-1)Harbor 与官方结果分歧标注

- R3.1 report.py 检测 Harbor 例行 verifier 与官方 Harness 结论分歧
  (二者均 COMPLETED 且 `verifier_outcome` 与 `resolved` 冲突),在 md
  渲染明确失败归属文字,如"官方 Harness 判定通过,但 Harbor 例行
  verifier 判失败(reward 0.0):判定以官方 Harness 为准,Harbor 侧仅
  过程证据,reward 不参与判定"。
- R3.2 reward 不参与判定(现有不变量)不变;JSON 维持原始字段
  (分歧可由 harbor/harness 两段推导),标注文字仅进 md 渲染。
- R3.3 验收:分歧场景(verifier_outcome=failed 且 resolved=true)报告
  含归属文字;一致场景(双通过/双失败)无标注。

## 3. 非目标(本 PR 不做)

- **不做 P1-4**(同一 payload 多次采样取均值、seed 化):属独立工作量,
  本 PR 只把阈值/门禁语义做扎实。
- **不做 Harbor verifier 失败重试**:P2-1 的"重试一次"为可选项,标注
  文字已满足验收;重试涉及 Harbor runner 行为变更,风险与收益不成
  比例,留待评估。
- 不改 verdict/退出码语义;不改 `DeepEvalResultFixture` 输入 schema
  (阈值是宿主侧策略常量,fixture 解析时按指标名补齐)。
- 不新增第三方依赖;不引入配置系统/新抽象层级。

## 4. 约束与红线

- 最小实现:模型字段一律带默认值(旧 JSON 可继续解析,
  `extra="forbid"` 只禁未知键,加可选字段不破坏);SCHEMA_VERSION 不变。
- 脱敏红线:judge 端点只进指纹哈希,不进报告原文;任何输出不含密钥。
- 不变量:DeepEval score_gate/Harbor reward 永远不参与 `task_result`
  判定与退出码。
- 源码注释中文;文档语言与现有 `docs/agent-e2e-verified-run.md` 一致。
- 最小验证:只跑与本次修改直接相关的 targeted tests。

## 5. 验收标准

- **A1(P1-3)**:`DeepEvalAnalysis` 带 `agent_model`/`judge_model`/
  `judge_fingerprint`,三者均可独立断言;md 展示 Agent/Judge 模型与指纹。
- **A2(P1-3 运维侧)**:`smoke.env.example`/README 增加
  `DEEPEVAL_JUDGE_MODEL`;`run_smoke.sh` 缺少该变量 rc=2;运行时显式传
  `--deepeval-judge-model`。
- **A3(P1-5)**:全过指标 → score_gate passed=True(3/3);部分低于阈值 →
  passed=False 且 `threshold_met` 逐项正确;全失败/无分 → score_gate
  None;解析旧 fixture 时阈值按常量补齐。
- **A4(P2-1)**:md 在分歧场景渲染归属文字;一致场景无标注
  (report.py 单测 + A5 报告复现)。
- **A5**:targeted 测试全绿(analysis/contracts/cli composition/smoke
  guard),`git diff --check` 通过,既有评测链测试不回归;本机按模板
  + `DEEPEVAL_JUDGE_MODEL` 复跑单题闭环,报告呈现新字段与门禁结论
  并勾销 backlog 三项。

## 6. 工作拆分建议

单任务单 PR,不拆父子任务(与 PR A/B 一致):一个行为边界内
(评分语义化 + 分歧标注)跨 models/analysis/runner/report/模板/文档/
测试,可独立理解与回滚。