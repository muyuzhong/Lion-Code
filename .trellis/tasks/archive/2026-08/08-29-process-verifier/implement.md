# Implement: 过程验证器(ProcessVerifier 确定性轨迹规则)

> 配套 `prd.md` / `design.md`。按序执行;每步完成即核对,进入下一步前
> 工作区干净(仅本任务改动)。

## 0. 前置

- 分支:从 master 新建 `eval-process-verifier`。
- 先读 `benchmarks/agent_e2e/trace.py`(`TraceEvent` 字段与
  `write_json` 格式)、`benchmarks/agent_e2e/models.py`
  (`TaskSpec.public_validation_commands` / `TaskResult` /
  `AgentRunSummary` / `TaskVerdict`)、`benchmarks/agent_e2e/regression.py`
  (仅参考 `_contains_marker` / `_tool_call_fingerprint` 的匹配思路,
  不导入私有函数)。

## 1. 新增 `benchmarks/agent_e2e/process_verifier.py`

- [ ] 1.1 `ProcessVerificationStatus` / `ProcessViolationType` /
      `ProcessSeverity` 枚举(violation / critical_veto)。
- [ ] 1.2 `ProcessViolation`(type / severity / evidence_offsets /
      description / extensions)。
- [ ] 1.3 `ProcessVerification`(task_id / attempt / outcome_verdict /
      status / violations / extensions);validator:status 与 violations
      聚合规则一致(design 3.1)。
- [ ] 1.4 `ProcessVerifier.__init__`:全部规则阈值与 marker 名单为构造
      参数(design 3.2 默认值)。
- [ ] 1.5 `verify(task, task_result, trace_events)`:预处理(排序 +
      sequence 唯一校验)→ 六条规则逐条评估 → 聚合 status。
- [ ] 1.6 六条规则内部函数(design 3.3 语义),各自返回 violations。
- [ ] 1.7 `verify_file(trace_path, task, task_result)` 便捷入口:
      读 harbor-trace.json(顶层 `events`),反序列化后调 verify。
- [ ] 1.8 `__all__` 导出公共符号。

## 2. 新增 `tests/benchmarks/test_process_verifier.py`

- [ ] 2.1 fixture:`TraceRecorder` + `record_tool_call` / 手工构造
      TraceEvent 合成轨迹(参考 test_trace.py 的构造方式);
      构造最小 TaskSpec / TaskResult(PASSED 与 FAILED 各一)。
- [ ] 2.2 repeated_tool_call:连续 3 次同调用触发、2 次不触发、
      argument_digest 不同不触发、None 参数不触发。
- [ ] 2.3 tool_error_not_recovered:错误事件后重复同调用触发;
      更换参数后不触发。
- [ ] 2.4 validation_missing:有验证命令且轨迹含 pytest 信号 → 不触发;
      有命令无信号 + PASSED → critical_veto;命令为空 → 跳过;
      FAILED 结果不触发。
- [ ] 2.5 test_tampering:写类工具 + 受保护 marker → critical_veto;
      非写工具不触发;无 marker 不触发。
- [ ] 2.6 premature_termination:stop_reason 含 max_turn/budget 触发;
      正常完成不触发。
- [ ] 2.7 context_regression:compaction 后首调用 == 压缩前失败调用
      触发;压缩后换策略不触发。
- [ ] 2.8 聚合:critical_veto 优先;violation 次之;空 → valid。
      同一轨迹两次 verify 结果一致(确定性)。
- [ ] 2.9 JSON round-trip:ProcessVerification 可 canonical_json /
      from_json。
- [ ] 2.10 `verify_file` 消费合成 harbor-trace.json 格式。

## 3. 验证

- [ ] 3.1 `python -m pytest tests/benchmarks/test_process_verifier.py -q`
      全绿。
- [ ] 3.2 `python -m pytest tests/benchmarks -q` 现有测试全绿
      (确认 classify_failure 契约零改动)。
- [ ] 3.3 `git diff --stat` 只动新增文件。

## 4. 提交

- [ ] 4.1 单次提交,message 如 `feat(benchmark): ProcessVerifier——全轨迹确定性过程判定(valid/violation/critical_veto)`。

## 5. 后续钩子

- 子任务一(paired-experiment-layer)合并后,在 `PairedTrial.extensions`
  挂接两侧 `ProcessVerification`(process_delta),形成四格 × 过程二维。
- 子任务三(comparison/gate V2)用 process 结果做 Process Regression。