# 回归门禁与失败回流设计

## 门禁输入与判定

门禁只比较同一冻结 catalog/task set、seed、repeats、timeout、budget、平台、Agent/verifier
镜像、evaluator revision 和资源上限下的 baseline/candidate 正式报告。允许变化仅限被明确声明的
`prompt_version`、`compression_version`、`tool_policy_version` 和相应 Agent code；模型、provider、
thinking、权限、预算、任务或 evaluator 改变均为 `invalid`，不允许计算 delta。

V1 默认规则：

- 非劣：candidate 成功率不能低于 baseline 10 个百分点。
- 灾难：三题 3/3 降至 0/3 无条件 `reject`。
- 分母：两边必须对全部冻结 task 各产生一个真实官方结果，且分母相等；blocked/offline/缺题均
  `invalid`。
- `waived` 必须有显式 waiver 原因；只有 `reject && !merged` 计入拦截账本。

门禁输出会明确标识 `self_only` 或 `external_calibrated`。没有覆盖这两个 profile 且阈值通过的
SWE-bench-Live 校准，只能说明自建回归集上的保护效果，不能声称泛化质量。

## 失败归因与回流

规则只处理已脱敏的 `TraceEvent`、`TraceSummary` 与 `TaskResult`：

| 候选模式 | 可审计信号 |
|---|---|
| 死循环 | 连续三次同 tool/arguments/workspace 指纹，记录 event sequence offsets |
| 上下文腐烂 | typed compaction/context-limit event 或 Agent context stop reason |
| 工具误用 | tool 不在本次允许集合、显式 tool/permission error event |
| 过早终止 | max-turns、max-cost、aborted/cancelled 等非完成 stop reason |
| 基础设施 | blocked/invalid 结果，优先于 Agent 行为标签 |

分类器只给候选标签与签名；复现状态、责任（Agent/evaluator/infrastructure/unknown）、去重和
是否准入由 review 记录决定。已复现、判定为 Agent 责任的失败可以生成新的 regression task；若
源任务来自 holdout，源 ID 必须被写入 retired-holdout 列表，不能继续保留为 holdout。V1 30 条
历史 corpus 不原地变更，回流进入下一 catalog 版本。

## 验收场景

1. 构造 3/3 到 0/3 的故意劣化 candidate，应 `reject` 且 ledger 拦截数 +1。
2. catalog、资源或有效分母不一致，应 `invalid`，不记拦截。
3. 四类 trace 规则以及 isolation/infrastructure 都有独立测试与 evidence offsets。
4. 复现的 holdout Agent 失败审核后生成新的 regression task，源 holdout 被 retire。
5. 无外部校准的 pass 明示 `self_only`；有效校准且覆盖两 profile 后才标记
   `external_calibrated`。
