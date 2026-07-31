# 编码 Agent 回归门禁与失败回流

本机制把 prompt、上下文压缩和工具策略的改动放进同一条可审计闭环：先在冻结的自建任务集上比较候选，再把已复现、已归因的失败安全地写入下一版 regression 集。它不把离线证据、Docker 不可用或未校准的结果包装成正式成功率或泛化结论。

## 回归门禁

调用 `evaluate_regression_gate()` 时，baseline 与 candidate 必须同时是完整的 `official` 报告，并且每个冻结任务、每次 repeat 都恰有一条有效的官方结果。门禁逐项检查：

- catalog ID、版本、SHA-256、任务选择和 catalog 扩展字段一致；
- seed、repeat、超时、预算、平台、镜像 digest、evaluator 代码、resume 状态和资源相关扩展字段一致；
- 模型、provider、thinking、权限、最大轮数、凭证变量名及 profile 扩展字段一致；
- 唯一允许的 profile 差异是已声明的 `prompt_version`、`compression_version`、`tool_policy_version`，对应 Agent 代码可以随这些变更更新；
- 两边都覆盖相同的有效分母。缺题、离线、blocked、invalid 或混入非官方结果都会得到 `invalid`，不会计算差值。

V1 默认采用 10 个百分点非劣边界：`candidate - baseline < -10pp` 为 `reject`。三题基线从 `3/3` 降至 `0/3` 是无条件的灾难性回退，也为 `reject`。`waived` 只能由调用方提供非空的明确豁免原因；不可比输入不能用豁免掩盖。门禁会保存配置比较指纹、两侧正式分数、delta 和声明的变更种类。

`RegressionGateLedger.intercepted_count` 只统计 `reject && !merged`。因此被错误地标成已合入的拒绝项不会夸大累计拦截数，账本可用 `write_gate_ledger()` / `load_gate_ledger()` 作为严格版本化 JSON 保存和读取。

## 外部锚点的结论范围

门禁默认标记为 `self_only`，即只证明该候选没有在自建冻结集上出现规定的回退。只有传入一个已接受的 `CalibrationReport`，它包含至少五个不同 profile、一个 baseline、至少三个 candidate、一个刻意退化 profile，满足相关性和方向一致性阈值，并且覆盖本次 baseline 与 candidate 的 profile 指纹时，才标记为 `external_calibrated`。

这不是运行 SWE-bench-Live 的替代品。实际校准仍须使用冻结的官方 evaluator、数据 revision 和镜像 digest；缺失这些输入时不能宣称外部泛化质量。

## 失败分类与审查

`classify_failure()` 只接收已经脱敏的 `TraceEvent`、`TaskResult` 和本次允许的工具名集合。它不会写入原始提示词、工具输出、工作区路径或凭证。规则生成候选标签及 `evidence_offsets`：

| 候选模式 | 受控证据 |
| --- | --- |
| `loop` | 连续三次同一工具、参数 digest 与工作区 fingerprint |
| `context_decay` | typed `context` / `compact` 事件或 Agent 的上下文停止原因 |
| `tool_misuse` | 不在允许集合中的工具，或 typed tool/permission error 事件 |
| `premature_termination` | max-turn、预算、abort、cancel 或 timeout 停止原因/事件 |
| `infrastructure` | blocked、invalid、offline_only；优先于 Agent 行为标签 |

候选并不是自动责任判定。`FailureTriage` 还必须记录复现状态、责任（Agent / evaluator / infrastructure / unknown）、审查理由和审查人。`deduplicate_failure_records()` 会按脱敏失败签名标注重复项，避免同一种已知失败无限复制进任务集。

## 反馈样本的防泄漏准入

`admit_failure_to_regression()` 仅接受同时满足以下条件的失败：

1. 已在冻结输入上复现；
2. 审查责任归属为 Agent；
3. 不是已去重的重复记录；
4. 新任务具有不同 ID、`regression` split 和 active 状态。

如果来源是 holdout，调用方必须同时把来源 ID 放入 retired-holdout 列表；返回的 `FeedbackAdmission` 会保证该 ID 不再出现在 active holdout 列表。原始 V1 历史 30 题不原地修改：反馈任务只应写入下一版 catalog，并由下一版的 corpus 准入检查验证。

## 建议的合入顺序

1. 冻结 baseline/candidate manifest 和官方结果；运行门禁。
2. 对 `reject` 且未合入的候选追加账本，观察累计拦截数。
3. 对失败轨迹执行规则分类，再完成人工复现和责任审查。
4. 仅将通过准入的反馈写入下一版 regression catalog；若源自 holdout，同时 retire 原 holdout。
5. 定期用冻结的 SWE-bench-Live 外部锚点校准多个 profile，才将通过结论从 `self_only` 升级为 `external_calibrated`。
