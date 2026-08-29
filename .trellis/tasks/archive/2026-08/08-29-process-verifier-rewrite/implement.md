# Implement: ProcessVerifier 重写——消费语义化过程证据

> 配套 `prd.md` / `design.md`。前置:子任务一(evidence.py)已合并。

## 0. 前置

- 分支:从 `eval-process-evidence`(或 master 合入后)新建
  `eval-verifier-rewrite`。
- 先读 `benchmarks/agent_e2e/evidence.py`(ProcessEvidence 字段)、
  `benchmarks/agent_e2e/process_verifier.py`(V1 现状)、
  `lion_code/core/events.py`(typed event 参考)。

## 1. 重写 `benchmarks/agent_e2e/process_verifier.py`

- [ ] 1.1 `ProcessVerificationStatus` 增加 `EVIDENCE_UNAVAILABLE`;
      `ProcessVerification._validate_status_aggregation` 更新为支持
      降级状态(design 3.1)。
- [ ] 1.2 `verify()` 增加 `evidence` 参数;evidence 空时立即返回
      EVIDENCE_UNAVAILABLE(不再跑文本规则)。
- [ ] 1.3 `_repeated_tool_call(evidence)`:按 tool_call_id 聚合 →
      call 级指纹 → 连续 ≥N 判定。
- [ ] 1.4 `_tool_error_not_recovered(evidence)`:基于 is_error=true
      的 end evidence。
- [ ] 1.5 `_validation_missing(task, task_result, evidence)`:基于
      validation_command 证据。
- [ ] 1.6 `_test_tampering(evidence)`:基于 tool_name + target_scope。
- [ ] 1.7 `_premature_termination(task_result, evidence)`:基于
      termination 证据 + stop_reason marker(保留)。
- [ ] 1.8 `_context_regression(evidence)`:基于 compaction 证据 +
      is_error 指纹对比。
- [ ] 1.9 `verify_file()`:读取 `evidence` 数组(缺失→空),透传。
- [ ] 1.10 删除 V1 文本 marker 匹配辅助函数(被证据规则替代);
      保留序列校验与聚合。

## 2. 修订 `tests/benchmarks/test_process_verifier.py`

- [ ] 2.1 helper:从 evidence.py 构造 ProcessEvidence;从
      lion_code.core.events 构造 typed event 走 TraceRecorder 投影
      生成 evidence(复用子任务一投影链路,保证真实)。
- [ ] 2.2 repeated_tool_call:一次 start/update/end 不触发;两个不同
      call 同指纹(连续 3 个 call)触发;两个 call 参数不同不触发。
- [ ] 2.3 tool_error_not_recovered:end+is_error 后续同指纹 call
      ≥2 触发;换参数不触发。
- [ ] 2.4 validation_missing:PASSED+有命令+无 validation 证据 →
      critical_veto;有证据 → 不触发;FAILED / 空命令 → 不触发。
- [ ] 2.5 test_tampering:写类工具 + scope∈{test,verifier} →
      critical_veto;source / 只读工具 → 不触发。
- [ ] 2.6 premature_termination:termination evidence 或 stop_reason
      marker → violation。
- [ ] 2.7 context_regression:compaction 后首个 call == 压缩前失败
      call → violation;换策略 → 不触发。
- [ ] 2.8 降级:evidence 空 → EVIDENCE_UNAVAILABLE + extensions 原因;
      不跑规则、不崩溃。
- [ ] 2.9 聚合与确定性:critical_veto 优先;同输入同输出;
      JSON round-trip(含新枚举值)。
- [ ] 2.10 verify_file:合成 harbor-trace.json(含 evidence)可解析;
      旧文件(无 evidence)→ EVIDENCE_UNAVAILABLE。

## 3. 验证

- [ ] 3.1 `pytest tests/benchmarks/test_process_verifier.py -q` 全绿。
- [ ] 3.2 `pytest tests/benchmarks -q` 全绿(环境性失败除外)。
- [ ] 3.3 ruff check 改动文件。

## 4. 提交

- [ ] 4.1 单次提交:`feat(benchmark): ProcessVerifier 重写为消费语义化证据——文本猜测规则整体替换,旧 trace 明确降级`。