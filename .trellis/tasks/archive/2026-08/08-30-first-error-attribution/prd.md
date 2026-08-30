# PRD: First-Error Attribution——成对轨迹对齐与首次偏离定位

> 来源:用户第六轮规划,PR 拆法 #148(本任务)。定位「第一次真正偏离
> 正确轨迹的地方」,为后续 regression_probe(下一 PR)提供可裁剪的
> 因果片段。**只做 first_error.py + 成对轨迹对齐 + first-error
> attribution + 测试;不做 corpus/runner/自动回流。**

## 1. 背景与目标

Gate V2 会输出 REGRESSED / BLOCKED,但只告诉我们「这个 Harness 改动
整体变差了」,没有告诉我们「从哪一步开始错」。本任务在
`PairedExperiment + ProcessEvidence + Gate V2` 之上加一层很薄的定位:

```text
baseline ProcessEvidence[]
candidate ProcessEvidence[]
        ↓ 对齐(调用级语义动作)
第一次 divergence
        ↓ 结合 ProcessVerifier 失败证据
first error attribution(因果片段)
```

核心原则:
- 不要「看到最终失败就从后往前挑最后一个异常」;
- 要的是「baseline 正常、candidate 从某一步开始结构性偏离」;
- 不是每个不同都是错误(candidate 换了一条同样有效的路径)——只有
  后续出现失败证据(未恢复错误 / critical veto / validation 缺失 /
  premature termination / pass→fail)才提升为 first error。

## 2. 需求

### 2.1 模型(最小两个)

```python
class FirstErrorKind(str, Enum):
    TOOL_SELECTION = "tool_selection"      # 不同工具
    TOOL_ARGUMENT = "tool_argument"        # 同工具不同指纹
    ERROR_RECOVERY = "error_recovery"      # tool error 且未恢复
    VALIDATION = "validation"              # validation 缺失/错误验证
    CONTEXT = "context"                    # compaction 后重复失败动作
    TERMINATION = "termination"            # premature termination
    PROCESS_VIOLATION = "process_violation"# critical veto(如 test_tampering)
    UNKNOWN = "unknown"

class FirstErrorAttribution(VersionedModel):
    task_id, attempt
    kind, confidence
    common_prefix_calls
    baseline_sequence, candidate_sequence   # first error 最早事件 sequence
    baseline_fingerprint, candidate_fingerprint
    baseline_events, candidate_events       # 因果片段(红acted 摘要行)
    reasons
```

### 2.2 算法

**第一步:调用级对齐。** 不按 sequence 硬对齐;把 ProcessEvidence 聚成
调用序列(按 tool_call_id 聚合,指纹取首个带参阶段),对齐键 =
`(tool_name, fingerprint)`;用共同前缀找出第一次 divergence。

**第二步:判断 divergence 是否真是错误。** 在 candidate 证据上复用
`ProcessVerifier`(传给它的 TaskResult 是 candidate 的),取 violations;
若 baseline 也有同类 violation,confidence 降低。

**第三步:按固定优先级定位 first error。**

```text
1. critical process violation (TEST_TAMPERING)  → PROCESS_VIOLATION
2. tool error 未恢复 (TOOL_ERROR_NOT_RECOVERED) → ERROR_RECOVERY
3. validation 缺失 (VALIDATION_MISSING)         → VALIDATION
4. compaction 后重复失败 (CONTEXT_REGRESSION)   → CONTEXT
5. premature termination                        → TERMINATION
6. 普通行为 divergence                           → TOOL_SELECTION/TOOL_ARGUMENT/UNKNOWN
```

无任何 violation 信号时:有 divergence 则返回低置信的行为 divergence
(confidence 0.4;若 pass→fail 则 0.6);无 divergence 返回 None。

### 2.3 输出因果片段

baseline_events / candidate_events 承载一个短片段,如:

```text
Baseline:
19 edit_file start fp=abcd1234
20 validation
21 finish PASS
Candidate:
19 edit_file start fp=efgh5678
20 edit_file end error=True
21 edit_file start fp=efgh5678
22 edit_file end error=True
23 finish FAIL
```

只含红acted 摘要行(sequence + tool_name + phase + fp 前 8 位 + error
标记 / validation / termination),不落盘路径或命令原文。

## 3. 非目标

- 不做 regression_probe / prefix minimization / corpus schema / runner
  (下一 PR #149);
- 不把 ProcessEvidence 落盘到 TaskResult(不扩执行链);
- 不做完整 Agent 重放或 SWE-bench 任务生成。

## 4. 验收标准

```text
1. 已知 bad case(candidate 同前缀后 edit 出错并重复同指纹,最终 fail)
   → 稳定定位 ERROR_RECOVERY,confidence 高,sequence 指向第一个 error
2. candidate 先 unrecovered error 后 premature termination
   → first error = ERROR_RECOVERY(不是最后的 TERMINATION)
3. candidate 写 test 文件(TEST_TAMPERING)→ PROCESS_VIOLATION,优先级最高
4. candidate 换工具/换参数但最终成功、无 violation
   → TOOL_SELECTION / TOOL_ARGUMENT,低置信,不判错误
5. 两条轨迹完全一致 → None
6. attribution 可 JSON 往返,因果片段不含原文
```

## 5. 文件

```text
benchmarks/agent_e2e/first_error.py
tests/benchmarks/test_first_error.py
```
