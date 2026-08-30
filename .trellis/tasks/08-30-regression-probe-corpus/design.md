# Design: Harness Regression Probe——regression_probe.py + regression_corpus.py

## 1. 数据流

```text
FirstErrorAttribution(#149)
        ↓  admission gate(evidence_available / confidence / 受支持 violation)
candidate ProcessEvidence
        ↓  minimize_failure_evidence(greedy 逐事件裁剪,probe_holds 判定)
最小失败片段
        ↓
RegressionCase(结构化 evidence + provenance + expected_*)
        ↓
RegressionCorpus  →  run_regression_corpus(逐条 verify_case 重放)
        ↓
RegressionCorpusReport(PASS / FAIL / INVALID)
```

## 2. regression_probe.py(最小化)

### probe_holds

```python
def probe_holds(
    violation_type: ProcessViolationType,
    evidence: Sequence[ProcessEvidence],
    task: TaskSpec,
    task_result: TaskResult,
    *,
    verifier: ProcessVerifier | None = None,
) -> bool:
    # 空 evidence → EVIDENCE_UNAVAILABLE,不是 violation
    if not evidence:
        return False
    verification = (verifier or ProcessVerifier()).verify(
        task=task, task_result=task_result, trace_events=(), evidence=evidence,
    )
    return any(v.violation_type is violation_type for v in verification.violations)
```

violation-aware 差异全部由 ProcessVerifier 承载:unrecovered error 需要
failed end + 后续同指纹 repeat;context regression 需要 failed end +
compaction + compaction 后同指纹 call;test_tampering 只需 write tool +
test/verifier scope。minimization 循环本身不感知 violation 结构。

### minimize_failure_evidence

```python
def minimize_failure_evidence(
    *,
    violation_type: ProcessViolationType,
    task: TaskSpec,
    task_result: TaskResult,
    evidence: Sequence[ProcessEvidence],
    probe: Callable[..., bool] | None = None,
    verifier: ProcessVerifier | None = None,
) -> tuple[ProcessEvidence, ...]:
```

- 按 sequence 排序后作为 current;
- 初始 current 不满足 probe → 抛 `ValueError`(调用方误用:minimize 只能
  作用于已成立 violation);
- greedy:每轮从 index 0 扫描,删除单个事件后 probe 仍成立则接受删除并
  从 0 重来;一轮无任何删除 → 收敛,返回当前片段;
- 结果满足:任何单事件删除都会破坏 violation(局部最小,确定性)。

## 3. regression_corpus.py(RegressionCase + 离线 runner)

### RegressionCase

```python
class RegressionCase(VersionedModel):
    case_id: str                     # 稳定标识
    source_task_id: str
    source_attempt: int
    source_run_id: str | None        # 溯源:run/experiment fingerprint
    first_error_kind: FirstErrorKind # 来源 attribution.kind
    expected_violation: ProcessViolationType
    expected_status: ProcessVerificationStatus
    evidence: tuple[ProcessEvidence, ...]   # 最小失败片段(结构化,非字符串)
    source_fingerprint: str          # attribution/case 溯源指纹
    original_evidence_count: int     # 最小化前事件数
    minimized_evidence_count: int    # 最小化后事件数
```

`expected_status`:minimize 后对最小片段重新 verify,由目标 violation 的
severity 推出(CRITICAL_VETO / VIOLATION),保证与重放结果一致。

### 入库判定

```python
_SUPPORTED_VIOLATIONS = frozenset({TEST_TAMPERING, TOOL_ERROR_NOT_RECOVERED,
    VALIDATION_MISSING, CONTEXT_REGRESSION, PREMATURE_TERMINATION,
    REPEATED_TOOL_CALL})

def attribution_can_enter_corpus(
    attribution, *, task, candidate_result, candidate_evidence, verifier=None,
) -> tuple[bool, str]:
    if not attribution.evidence_available: return False, "..."
    if attribution.confidence < 1.0: return False, "..."
    # 以实际 violation 为准(REPEATED_TOOL_CALL 的 kind=UNKNOWN 有歧义)
    verification = verifier.verify(...)
    if not (支持violations ∩ 实际violations): return False, "..."
    return True, ""

def regression_case_from_attribution(...) -> RegressionCase | None:
    # 1) attribution_can_enter_corpus;2) 目标 violation(优先与 kind 一致,
    #    否则按优先级最早);3) minimize;4) 重 verify 推 expected_status;5) 建 case
```

### 离线 runner

```python
class RegressionCaseStatus(str, Enum): PASS / FAIL / INVALID

class RegressionCaseResult(VersionedModel):
    case_id; status; passed: bool
    expected_violation; actual_violations
    expected_status; actual_status
    reason

class RegressionCorpusReport(VersionedModel):
    total; passed; failed; invalid
    results: tuple[RegressionCaseResult, ...]

def run_regression_corpus(
    cases: Sequence[RegressionCase],
    *,
    verifier: ProcessVerifier | None = None,
) -> RegressionCorpusReport:
    # 每条:case 自带 ProcessReplayContext → verifier.verify_case(evidence)
    # 判定:expected_violation 在 actual_violations 中 且 expected_status 匹配 → PASS
    #       否则 FAIL;evidence 空/verify_case 返回 EVIDENCE_UNAVAILABLE → INVALID
```

## 4. process_verifier.py 扩展(自包含重放)

```python
class ProcessReplayContext(VersionedModel):
    verdict: TaskVerdict | None = None
    stop_reason: str | None = None
    public_validation_commands: tuple[str, ...] = ()
```

- `verify()` 与 `verify_case()` 共享私有 `_verify_shared(...)`;规则函数
  `_validation_missing` / `_premature_termination` 改为消费极简内部
  context(`verdict / stop_reason / validation_commands`),不再依赖完整
  模型;
- `verify_case(evidence, *, context=None, task_id="replay")`:
  `outcome_verdict=context.verdict`,attempt=None,规则与 verify 完全一致;
- `verify()` 公开行为不变(测试回归保护)。

## 5. 边界与契约

- corpus 只存结构化 ProcessEvidence + 摘要类字段;路径/命令原文绝不进入
  evidence(继承 evidence.py 隐私不变式);
- minimize 是纯函数、确定性;同输入同输出;
- 不修改 `attribute_first_error`(#149)与 `ProcessVerifier.verify` 行为;
- 新增符号进 `benchmarks/agent_e2e/__init__.py` 的 `__all__`;
- spec(`.trellis/spec/backend/agent-e2e-evaluation.md`)补充 Regression
  Probe / RegressionCase / verify_case 契约。

## 6. 测试要点

- probe:unrecovered error 长轨迹裁短仍成立;删必要事件后不成立;
  test_tampering 单事件即可;空 evidence False;
- corpus:confidence<1.0 拒绝;evidence_available=False 拒绝;
  PASS→PASS 无 attribution 无法入库;JSON round-trip;
- runner:固定 case 两次运行结果一致(确定性);PASS/FAIL/INVALID 三态。
