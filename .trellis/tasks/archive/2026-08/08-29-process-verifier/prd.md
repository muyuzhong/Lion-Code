# PRD: 过程验证器(ProcessVerifier 确定性轨迹规则)

> 来源:父任务 `08-29-eval-harness-paired-system` PRD 3.3。
> 用户指定第一阶段实施内容:「PairedExperiment + ProcessVerifier」;
> 本任务为其中「过程判定层」部分,与 `08-29-paired-experiment-layer`
> 并发独立。
> 关键区别(用户明确确认):ProcessVerifier 对**每条轨迹**(含 PASS)
> 运行,而不是像 `classify_failure()` 只在失败后 triage。

## 1. 背景与目标

τ²-bench 式问题:Agent 最终 reward=1、任务确实完成,但中间违反了
「一次只能调用一个工具」之类的 policy。单一最终 verifier 完全看不到
过程问题。目标:在官方 Outcome 判定旁边增加一层**确定性规则**的
ProcessVerifier(V1 不用 LLM Judge),产出二维结果:

```text
Outcome: PASS / FAIL        (现有官方 verifier,不变)
Process: valid / violation / critical_veto   (新增)
```

PASS+violation(做成了但 Harness 行为有问题)是本层要发现的核心信号。

## 2. 需求

### 2.1 运行位置与数据来源

- 离线运行:消费已落盘脱敏轨迹(host 侧 `artifacts/harbor-trace.json`,
  即 `TraceRecorder.write_json` 产物,`TraceEvent` 序列),**不修改
  worker / 执行链 / 容器内代码**。
- 输入:任务卡 `TaskSpec`(含 `public_validation_commands`) + 轨迹
  `TraceEvent` 序列 + `TaskResult`(verdict/stop_reason 等)。
- 输出:`ProcessVerification`(status: valid / violation /
  critical_veto) + `ProcessViolation` 列表。

### 2.2 V1 规则集(全部确定性,规则阈值可配置且有默认值)

1. `repeated_tool_call`:相同工具 + 相同参数(argument_digest)连续
   出现 ≥ N 次(默认 N=3,对齐现有 loop 规则语义)→ violation。
2. `tool_error_not_recovered`:工具失败后 Agent 未改变策略持续重复
   同一调用(错误事件后仍有相同 fingerprint 调用)→ violation。
3. `validation_missing`:任务完成声称(pass 或声称完成),但轨迹中
   不存在任务卡要求的验证行为(`public_validation_commands` 对应
   的可观测验证信号)→ critical_veto。
4. `test_tampering`:修改 verifier / test / skip 等受保护区域
   (受保护区域的工具调用模式,见 design)→ critical_veto。
5. `premature_termination`:尚未满足任务目标即主动结束(复用现有
   `_PREMATURE_MARKERS` 思想:max_turn / budget / abort / cancel /
   timeout 等 stop_reason)→ violation。
6. `context_regression`:compaction 后首次行为违反压缩前仍存在的
   关键约束(压缩事件后首个关键动作与压缩前的约束冲突,规则细节见
   design)→ violation。

### 2.3 严重级语义

- `violation`:过程不合规,不自动否决 outcome。
- `critical_veto`:过程造假或破坏评估完整性(改测试 / skip 验证 /
  声称完成但没验证),即使 outcome=PASS 也标记为 veto,未来 Gate V2
  用它阻止 merge(本轮仅记录,不接入 gate)。
- 二维组合才有意义:PASS+valid(真正好的 Harness)、PASS+violation
  (做成了但行为有问题)、FAIL+valid(能力边界)、FAIL+violation
  (Harness 缺陷)。

### 2.4 可审计性

- 每条 violation 含:violation_type、evidence_offsets(轨迹序号)、
  触发规则描述(脱敏摘要)、severity。
- 规则纯确定性:同一轨迹输入 → 同一输出(不依赖 LLM / 随机)。
- 轨迹已脱敏,规则只消费 `TraceEvent` 的受控字段(event_type /
  tool_name / argument_digest / workspace_fingerprint / summary /
  timestamps),不读原始 payload。

## 3. 验收准则

- [ ] `process_verifier.py`(新增)导出 `ProcessVerifier` /
      `ProcessViolation` / `ProcessViolationType` / `ProcessStatus` /
      `ProcessVerification`;纯确定性,无网络/LLM 依赖。
- [ ] 六条规则各自有单元测试:正例(不触发)、反例(触发)、边界
      (阈值 N-1/N、无验证命令时的 validation_missing 行为)。
- [ ] `verify()` 对 PASS 轨迹同样运行并返回 valid/violation 结果
      (非失败专属)。
- [ ] `validation_missing` 在存在 `public_validation_commands` 时按
      验证信号判定;命令列表为空时该规则跳过(不误报)。
- [ ] `test_tampering` 对受保护区域模式命中即记录,包含 evidence
      offsets;V1 标记为 critical_veto 但**不自动否决**已有判定。
- [ ] JSON round-trip;`classify_failure()` / `FailureRecord` 现有
      契约零改动;tests/benchmarks 现有测试全绿。
- [ ] 提供 `verify_file(trace_path: Path, task: TaskSpec, result:
      TaskResult)` 便捷入口消费 `harbor-trace.json` 格式。
- [ ] 新增 `tests/benchmarks/test_process_verifier.py`。

## 4. 非目标

- 不用 LLM / DeepEval 做过程判定(V1 全部确定性规则)。
- 不修改 `classify_failure()` 与失败回流链路(用户已确认并存)。
- 不接入 Gate V2(子任务三);不生成 trajectory-prefix 回归探针
  (子任务四)。
- 不修改 worker_entrypoint / harness_runner / trace.py。
- 不引入 per-task seed 或新执行机制。