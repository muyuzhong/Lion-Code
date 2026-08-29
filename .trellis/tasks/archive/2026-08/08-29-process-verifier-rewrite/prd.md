# PRD: ProcessVerifier 重写——消费语义化过程证据

> 来源:父任务 `08-29-eval-fidelity` 3.2。前置:子任务一
> (process-evidence-projection)交付 `ProcessEvidence` 数组。
> 目标:六条规则从「猜脱敏文本」改为「读明确事实」。

## 1. 背景与目标

V1 ProcessVerifier(PR #143)的六条规则基于 event_type / summary /
tool_name 的文本 marker 匹配,在真实数据上实测失效:
- `tool_execution_end` 无 `is_error` 字段 → `tool_error_not_recovered`
  永不触发;
- summary 无命令文本 → `validation_missing` 找不到 pytest;
- 路径哈希 → `test_tampering` 无法判断 scope;
- 无 tool_call_id 聚合 → 一次调用的 start/update/end 可能被误判为
  重复调用。

重写目标:六条规则消费子任务一落盘的语义化 `ProcessEvidence`,
每条规则基于确定的字段判定;聚合语义(critical_veto 优先 / violation
次之 / valid)与「不改变 outcome」的分离原则保持不变。

## 2. 需求

### 2.1 规则重写映射

| 违规 | V1(猜文本) | V2(读证据) |
|---|---|---|
| repeated_tool_call | 连续 N 个同 tool+digest 事件 | 按 `tool_call_id` 聚合生命周期;**不同 call** 的同 fingerprint 连续 ≥ N 次才算重复 |
| tool_error_not_recovered | event_type 含 error marker | `tool_phase=end` 且 `is_error=true` 后,同 fingerprint 的后续调用继续 |
| validation_missing | summary 含命令名 | 轨迹中无 `validation_command=true` 的 evidence(PASSED 且任务声明命令时) |
| test_tampering | tool_name + 文本 marker | `target_scope ∈ {test, verifier}` 且工具为写类 |
| premature_termination | stop_reason / event marker | `termination` evidence(turn_failed / cancelled / 预算轮数) |
| context_regression | compaction marker + 前后指纹 | `compaction=started/completed` 后首个调用与压缩前失败指纹相同 |

### 2.2 接口与语义

- `ProcessVerifier.verify()` 输入升级:可同时接受 `evidence` 数组与
  `trace_events`(证据优先;证据缺失时降级,见 2.3)。
- `ProcessViolation` / `ProcessVerification` 模型与聚合规则不变
  (schema 兼容,不破坏 PR #143 已落地的契约)。
- `verify_file()` 升级:读取 `harbor-trace.json` 的 `evidence` 数组;
  无 evidence 的旧文件 → 明确降级标记。

### 2.3 旧数据降级策略

- 无 evidence 时:**不推断、不乱判**。输出
  `status=evidence_unavailable`(新枚举值,不并入 valid/violation/
  critical_veto 的聚合),并记录原因「旧 trace 无语义证据」。
- 降级不改变 `TaskResult.verdict`,不影响已有报告的官方判定。
- 历史 trace 上的回顾性分析明确标注为「低置信度」。

## 3. 验收准则

- [ ] 六条规则映射全部实现:每条规则有正例(触发)/反例(不触发)/
      边界测试;测试基于 `ProcessEvidence` 构造而非文本 marker。
- [ ] repeated_tool_call:一次调用 start+update+end 不得触发;不同
      call 同指纹连续 N 次触发。
- [ ] tool_error_not_recovered 只基于 `is_error=true` end 事件;
      validation_missing 只基于 `validation_command` evidence;
      test_tampering 只基于 `target_scope`;premature 只基于
      `termination`;context_regression 只基于 `compaction`。
- [ ] 无证据降级:旧文件 verify 输出 `evidence_unavailable` 且不崩溃;
      新枚举不破坏既有聚合与序列化。
- [ ] `verify_file` 消费 evidence 数组;JSON round-trip 通过。
- [ ] 确定性:同一输入两次 verify 结果一致。
- [ ] 现有 test_process_verifier.py V1 文本匹配类用例按新语义修订;
      tests/benchmarks 全绿。

## 4. 非目标

- 不新增规则类型(仍为六条)。
- 不做真实 trace 校准(子任务三)。
- 不修改 `classify_failure()` 与失败回流链。
- 不改变 ProcessVerification 聚合优先级(除非降级枚举需要,
  由 design 决定最小方案)。