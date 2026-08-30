# Design: First-Error Attribution——first_error.py

## 1. 数据流

```text
baseline ProcessEvidence[]  ─┐
candidate ProcessEvidence[] ─┴→ attribute_first_error()
        ├─ 调用级对齐 → 第一次 divergence
        ├─ ProcessVerifier.verify(candidate) → violations
        ├─ 固定优先级选 first error → kind + sequence + confidence
        └─ 因果片段(红acted 摘要行)
        ↓
FirstErrorAttribution | None
```

## 2. 数据结构

### 调用聚合(内部)

```python
@dataclass(frozen=True)
class _Call:
    tool_name: str
    fingerprint: str            # 首个带参阶段(start/update)的 tool_fingerprint
    start_sequence: int         # 该调用最早 evidence sequence
    sequences: tuple[int, ...]  # 该调用全部 evidence sequence
```

聚合规则:按 tool_call_id 分组,按首次出现顺序;fingerprint 取该 call
第一个 `tool_phase in {START, UPDATE}` 且带 tool_fingerprint 的事件;
无 tool_call_id 的 evidence(validation/termination/compaction)不参与
对齐(它们不构成语义动作),但参与 ProcessVerifier 错误信号。

### 对齐键

`(tool_name, fingerprint or "<no-fp>")`。共同前缀 = 从两侧序列开头逐
个比较直到不同或一侧耗尽。

### 第一次 divergence

```text
共同前缀 = k
若两侧都有第 k 个调用:
  tool_name 不同           → TOOL_SELECTION
  tool_name 相同指纹不同    → TOOL_ARGUMENT
若一侧耗尽(插入/删除)      → UNKNOWN(附 reasons)
```

divergence 的 baseline_sequence / candidate_sequence = 两侧第 k 个
调用的 start_sequence;fingerprint = 两侧第 k 个调用指纹。

## 3. 错误信号与优先级

复用 `ProcessVerifier()`(默认阈值)在 candidate evidence 上跑:

```python
verification = ProcessVerifier().verify(
    task=task, task_result=candidate_result, trace_events=(), evidence=candidate_evidence
)
```

violation_type → kind + 优先级(数字越小越优先):

```python
TEST_TAMPERING            → (0, PROCESS_VIOLATION)
TOOL_ERROR_NOT_RECOVERED  → (1, ERROR_RECOVERY)
VALIDATION_MISSING        → (2, VALIDATION)
CONTEXT_REGRESSION        → (3, CONTEXT)
PREMATURE_TERMINATION     → (4, TERMINATION)
REPEATED_TOOL_CALL        → (5, UNKNOWN)
```

取优先级最高(数字最小)的 violation;同优先级取最早 `evidence_offsets`。
`candidate_sequence` = 该 violation 最早 evidence_offset。

confidence:

```text
candidate 有 violation 且 baseline 无同类   → 1.0
candidate 有 violation 但 baseline 也有同类  → 0.7
无 violation + baseline PASS → candidate FAIL + 有 divergence → 0.6
无 violation + PASS→PASS 的行为分歧          → None(不同实现路径不是 first error)
无 divergence → None
```

PASS→PASS 的 harmless divergence 不产出 attribution,避免污染
regression_probe 的回归语料。

## 4. 因果片段

`_snippet(evidence_sorted, start_index, count)` 从指定位置取连续 count
条 evidence 的摘要行。窗口选择:

```text
candidate_events: 从 min(divergence_seq, error_seq) 起连续 6 条
baseline_events:  从 baseline divergence 位置起连续 4 条(仅在有 divergence 时)
```

摘要行(红acted):

```text
"{seq} {tool_name} {phase} fp={fp[:8]}"      # 工具 start/update
"{seq} {tool_name} end error=True"           # 工具 end 错误
"{seq} validation"                            # validation_command=True
"{seq} termination={kind}"
"{seq} compaction={state}"
```

路径/命令原文一律不出现。

## 5. 接口

```python
def attribute_first_error(
    *,
    task: TaskSpec,
    candidate_result: TaskResult,
    baseline_result: TaskResult | None = None,
    baseline_evidence: Sequence[ProcessEvidence] = (),
    candidate_evidence: Sequence[ProcessEvidence] = (),
) -> FirstErrorAttribution | None
```

## 6. 测试

- 已知 bad case:同前缀 + edit error 重复 → ERROR_RECOVERY,confidence 1.0,
  candidate_sequence 指向第一个 error;
- 优先级:unrecovered error + premature termination → ERROR_RECOVERY;
- PROCESS_VIOLATION 最高优先级;
- 行为 divergence 无错误 → TOOL_SELECTION/TOOL_ARGUMENT 低置信;
- 完全一致 → None;
- validation missing(PASSED 无验证)→ VALIDATION;
- JSON 往返 + 片段无原文。

## 7. 不做的事

- 不碰 regression_probe / corpus / runner(下一 PR);
- 不落盘 ProcessVerification 到 TaskResult;
- 不新增抽象基类 / Manager。
