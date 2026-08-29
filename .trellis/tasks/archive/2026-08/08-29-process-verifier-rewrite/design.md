# Design: ProcessVerifier 重写——消费语义化过程证据

> 配套 `prd.md`。记录边界、规则映射、降级策略与取舍。

## 1. 涉及面与边界

| 文件 | 动作 |
|---|---|
| `benchmarks/agent_e2e/process_verifier.py` | **重写规则层**:六条规则消费 `ProcessEvidence`;`ProcessVerificationStatus` 增加 `EVIDENCE_UNAVAILABLE`;`verify_file` 读 evidence 数组 |
| `benchmarks/agent_e2e/evidence.py` | **只读复用**(父任务产出) |
| `benchmarks/agent_e2e/trace.py` | 只读复用(TraceEvent 仍用于 sequence 对齐) |
| `tests/benchmarks/test_process_verifier.py` | **修订**:V1 文本匹配用例改为证据构造;新增降级用例 |

## 2. 数据流

```
verify(task, task_result, trace_events, *, evidence=())
        │
        ├── evidence 非空 → 六条证据规则 → 聚合(不变)
        │
        └── evidence 空 → status = EVIDENCE_UNAVAILABLE(不猜)
```

## 3. 具体设计

### 3.1 降级枚举(最小方案)

```python
class ProcessVerificationStatus(str, Enum):
    VALID = "valid"
    VIOLATION = "violation"
    CRITICAL_VETO = "critical_veto"
    EVIDENCE_UNAVAILABLE = "evidence_unavailable"
```

- `EVIDENCE_UNAVAILABLE` **不参与**聚合排序:当且仅当证据为空时
  输出;并放入 `ProcessVerification.extensions["degraded_reason"] =
  "旧 trace 无语义证据"`。
- 与 PR #143 契约兼容:模型增枚举值(向后兼容序列化),聚合 validator
  改为「有 violations 时按原优先级;否则 evidence 为空且非降级…
  不允许」——具体:若 violations 非空则按严重级;若 violations 空,
  status 必须为 VALID 或 EVIDENCE_UNAVAILABLE(空证据+VALID 视为
  旧调用方传参错误)。

### 3.2 verify() 签名与规则重写

```python
def verify(self, *, task, task_result,
           trace_events: Sequence[TraceEvent],
           evidence: Sequence[ProcessEvidence] = ()) -> ProcessVerification
```

规则实现(全部以 evidence 为准,trace_events 仅用于降级判定与
sequence 校验):

1. **repeated_tool_call**:按 `tool_call_id` 分组聚合生命周期,
   每个 call 只取一次指纹(start 指纹);不同 call 的相同指纹连续
   (按 sequence 序) ≥ N 次 → violation。
2. **tool_error_not_recovered**:`tool_phase=end` 且 `is_error=true`
   的 evidence 之后,同 fingerprint 的后续新 call 继续
   ≥ error_repeat_threshold → violation。
3. **validation_missing**:`task_result.verdict==PASSED` 且任务声明
   验证命令非空,而 evidence 中无 `validation_command=true` →
   critical_veto。
4. **test_tampering**:evidence.tool_name ∈ write_tool_names 且
   `target_scope ∈ {test, verifier}` → critical_veto。
5. **premature_termination**:evidence.termination ∈
   {turn_failed, cancelled} 或 stop_reason 含预算/轮数 marker →
   violation。
6. **context_regression**:最后一个 `compaction=completed`(或
   started,取二者最近者)之后的首个 tool evidence,与 compaction
   前最近一次 `is_error=true` 调用指纹相同 → violation。

聚合逻辑不变(critical_veto 优先 → violation → valid);
证据为空时直接返回 EVIDENCE_UNAVAILABLE,不运行规则。

### 3.3 verify_file 升级

```python
def verify_file(trace_path, *, task, task_result,
                verifier=None) -> ProcessVerification:
    payload = json.load(...)
    evidence = tuple(ProcessEvidence.from_dict(e)
                     for e in payload.get("evidence", []))
    events = tuple(TraceEvent.from_dict(e) for e in payload.get("events", []))
    return verifier.verify(task=task, task_result=task_result,
                           trace_events=events, evidence=evidence)
```

- 旧文件(`evidence` 键缺失)→ 空 evidence → EVIDENCE_UNAVAILABLE。

### 3.4 与 classify_failure 的关系

不变:两系统并存互不调用;classify_failure 及其回流链零改动。

## 4. 取舍

- 文本 marker 规则**整体替换**为证据规则(不保留双轨):否则两套
  语义并存会造成判定不一致;PR #143 的 V1 文本测试相应重写(它们
  本来就是合成用例,改为证据构造即可)。
- `EVIDENCE_UNAVAILABLE` 独立枚举值而非塞进 extensions:可被
  校准/报告直接识别,避免字符串约定。
- repeated_tool_call 按「call 级指纹」而非「事件级」:一次调用的
  start/update/end 生命周期不会误判(用户核心诉求)。

## 5. 验证命令

- `pytest tests/benchmarks/test_process_verifier.py -q`
- `pytest tests/benchmarks -q`