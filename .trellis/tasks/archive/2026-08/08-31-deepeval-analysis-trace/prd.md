# DeepEval 安全语义工具轨迹

## Goal

新增一份只面向 DeepEval 的安全语义工具轨迹，让 DeepEval 能判断 Tool Argument 与 Tool Decision；除此之外，不改变现有 `ProcessEvidence`、`ProcessVerifier`、官方判定和整体评测架构。

## Background and Confirmed Facts

- 现有 Verified 链已经完成三条不同 SWE-bench Verified 实例的官方 `3/3` 通过，证明 `Lion Code → Harbor → 官方 Harness → DeepEval → Opik` 的工程链路可用；样本量不足以支持能力强弱结论。
- 当前 `DeepEvalTrajectoryEvent` 主要保留工具名和 digest，传给 DeepEval 的 `ToolCall` 没有可判断的安全参数，因此 Judge 无法可靠评价参数或错误后的工具选择。
- `ProcessEvidence` 是确定性、安全、可审计的规则输入，已被 `ProcessVerifier`、First-Error Attribution 和 Evidence Regression Corpus 使用。本任务不改变其模型、归属、序列化或调用方式。
- 项目固定 `deepeval==4.2.0`。`ArgumentCorrectnessMetric` 可在没有逐步工具金标时判断调用参数；`ToolCorrectnessMetric` 需要 `expected_tools`，当前 SWE-bench 轨迹没有这类金标。
- Lion 当前没有安全、稳定的结构化计划事件，本阶段不启用 PlanQuality/PlanAdherence。
- 现有三条成功运行的旧 `harbor-trace.json` 不含可逆参数和工具结果，不能事后生成语义轨迹；实现后需要重跑才能成为正样本。

## Requirements

### R1. 只新增 DeepEval 专用 Analysis Trace

- worker 从现有 typed Core event 流投影独立的 `analysis-trace.json`，不向 `ProcessEvidence` 或现有 `TraceEvent` 增加字段，也不解析 stdout/session 日志补数据。
- 数据单位保持为按原始 `sequence` 排序的 semantic tool call/result；不引入 `AnalysisDecision` 或任何人为 decision window。
- 首版只需要一个严格、有界、版本化的 `AnalysisTrace` 和一种有序事件记录，保留 `sequence`、`tool_call_id`、工具名以及安全语义参数或结果。
- 新产物只服务 DeepEval。Opik 继续使用现有输入与 span 结构。

### R2. 隐私边界严格先于诊断丰富度

- 工作区路径只保存规范化相对路径；绝对路径、工作区外路径、Verifier/gold/hidden 路径不得明文出现。
- `run_shell` 不保存原始 command，只保留确定性识别出的命令族、子命令、安全相对目标、必要受控选项、exit code、测试计数和错误类型。例如允许表达“运行 pytest，目标 tests/test_config.py，结果 ModuleNotFoundError”。
- 文件读取与搜索只保留安全相对目标及长度受限、凭证过滤后的必要参数；写入与编辑不保存源码正文。
- 工具结果不保存任意 stdout/stderr，只保留结构化事实及长度受限、路径和凭证过滤后的错误类型/摘要。
- 未识别工具或命令降级为 `other`、安全参数键名和 digest，不猜测语义，不泄露原值。

### R3. DeepEval 第一阶段只有两个诊断结果

- 用 `ArgumentCorrectnessMetric` 判断安全语义工具参数是否适合任务与当时上下文。
- 用窄化的 `ToolDecisionQuality` GEval 判断工具选择、顺序、无关绕路以及观察到错误后的下一步是否合理。
- 两个指标都读取公开任务和按 `sequence` 排序的 Analysis Trace，不读取 hidden reasoning。
- 复用现有 `DeepEvalMetricResult` 和错误/超时/partial 处理，不新增 `DeepEvalFinding`、`DeepEvalDiagnosis` 或统一诊断层。
- 指标 reason 应引用相关 `sequence`；第一阶段不增加额外的 finding wire model，也不合成“主归因”。
- 不运行 `ToolCorrectnessMetric`、PlanQuality、PlanAdherence，也不把旧 `TaskCompletion`、`StepEfficiency`、`TrajectoryQuality` 继续作为本阶段主要 DeepEval 输出。

### R4. 最小运输与报告改动

- worker/Harbor 只负责把 `analysis-trace.json` 作为受控附加产物带到现有 host 后处理。
- DeepEval adapter 只消费经 schema 校验的 Analysis Trace；旧运行缺少该产物时返回现有 typed unavailable/partial 状态，不尝试逆转 digest。
- JSON/Markdown 报告沿用现有 DeepEval 结果结构，展示 Tool Argument 与 Tool Decision 两项的 status、score、reason 和 reason 中的 sequence 引用。
- 官方 Harness 结论和 `TaskResult.verdict` 始终优先且不受 DeepEval 成功、失败、超时或缺失影响。
- 不修改 `ProcessVerifier` 的模型、运行位置或报告合成；不新增 DeepEval 与 ProcessVerifier 的联合归因；不修改 Opik span 或 feedback 投影。

### R5. 只验证方向性价值

- 单元/集成测试至少覆盖：安全相对路径、pytest 目标与错误类型、合理恢复、无效参数调整、错误工具选择、无关文件绕路、未知工具降级和隐私负例。
- 使用相同任务上下文构造“合理版本”和“人为退化版本”，要求两个指标给出符合方向的差异，不断言固定绝对分。
- 实现后在同一冻结环境重跑现有三条官方通过实例，作为真实正样本；历史失败原始事件可用时再补充，否则使用明确标注的合成退化轨迹。
- 校准记录 Judge 模型、指纹、采样数和分数范围。Analysis Trace 价值尚未证明前，不扩展 diagnosis、planning 或 Opik 集成。

## Acceptance Criteria

- [ ] 现有 `harbor-trace.json`、`ProcessEvidence` 和 `ProcessVerifier` 的 schema、模型归属与行为保持不变；新增 `analysis-trace.json` 能从 worker 安全到达 host 后处理。
- [ ] Analysis Trace 只包含按原始 `sequence` 排序的 semantic tool call/result，不存在 `AnalysisDecision` 或人为 decision 边界。
- [ ] Analysis Trace round-trip 具有严格 schema、稳定 digest、事件上限和显式 truncated/unavailable 状态。
- [ ] 安全测试证明产物不含绝对路径、工作区外/Verifier 路径、原始 shell command、源码/编辑正文、任意 stdout/stderr、prompt、reasoning 或注入的 secret；同时保留安全相对路径、pytest 目标和 `ModuleNotFoundError` 等必要语义。
- [ ] DeepEval 4.2.0 只输出 `ArgumentCorrectnessMetric` 与 `ToolDecisionQuality` 两个现有类型的 metric result；reason 可回指相关 sequence。
- [ ] 不新增 `DeepEvalFinding`、`DeepEvalDiagnosis`、ProcessVerifier wire model 迁移、联合归因或聚合 DeepEval pass/fail gate。
- [ ] 未提供 `expected_tools` 时不运行或伪造 `ToolCorrectnessMetric`；不启用 PlanQuality/PlanAdherence。
- [ ] 报告先展示不变的官方结果，再展示两项 DeepEval 诊断的 status、score、reason；DeepEval 任意失败都不改变官方结果。
- [ ] 合理轨迹相对人为退化轨迹呈现方向一致的 Tool Argument/Tool Decision 差异，并记录 Judge 运行元数据。
- [ ] 当前三条官方通过任务在新实现下重跑并产出语义轨迹；若外部环境、凭证或任务 ID 不可用，明确报告 blocked，不用旧 digest 轨迹冒充验收。

## Out of Scope

- `ProcessVerifier` 模型迁移、调用重构、与 DeepEval 的联合归因或统一 diagnosis synthesis。
- `AnalysisDecision`、decision window、`DeepEvalFinding`、`DeepEvalDiagnosis` 或新的报告领域模型。
- Opik trace tree、span、feedback 或 Analysis Trace 消费改造。
- PlanQuality、PlanAdherence、hidden reasoning/thinking 持久化或计划提取。
- Baseline/Candidate 语义轨迹差分、统计显著性、批量调度、通用 metric/plugin registry。
- 自动生成 expected tools、DeepEval 数据集生成、Confident AI 上报、修改 Lion Runtime/Tool API 或让 Judge 参与官方 pass/fail。

## Deferred Items and Risks

- Judge 的 sequence 引用由受控 rubric 和有序输入约束，但仍是 advisory 文本；只有校准证明需要机器可读引用时，才考虑新增最小结构化字段。
- 当前三条通过任务的 task ID 与运行产物不在 checkout 中；真实验收需要从外部运行记录取得 ID 并重跑。
- Analysis Trace 只验证两个动作诊断是否有价值。若方向性校准不稳定，本阶段应调整投影或 rubric，而不是增加更多模型和指标。
