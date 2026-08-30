# Design: Evidence Regression Corpus——regression_probe.py + evidence_regression_corpus.py

> 语义收口(评审后):本层是 **Evidence Regression Corpus**,不是 Harness
> 行为回归语料。离线重放同一份历史 evidence 经过同一个 ProcessVerifier,
> 只能验证检测规则本身没有退化;它不执行生产 Harness 逻辑,不能证明改过
> 的 Harness 不会再产生该错误。

## 1. 数据流

```text
FirstErrorAttribution(#149)
        ↓  admission gate(evidence_available / confidence / 受支持 violation)
candidate ProcessEvidence
        ↓  minimize_failure_evidence(greedy 逐事件裁剪,probe_holds 判定)
单事件不可再约简片段(1-minimal)
        ↓
EvidenceRegressionCase(结构化 evidence + provenance + replay_context)
        ↓
Evidence Regression Corpus → run_evidence_regression_corpus(逐条 verify_case 重放)
        ↓
EvidenceRegressionCorpusReport(PASS / FAIL / INVALID)
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
- 结果保证 **1-minimal**(删除最终片段中任意一个事件,violation 都不再
  成立),不是全局最短;不引入组合搜索或复杂 delta debugging。

## 3. evidence_regression_corpus.py(EvidenceRegressionCase + 离线 runner)

### EvidenceRegressionCase

```python
class EvidenceRegressionCase(VersionedModel):
    case_id: str                     # 稳定标识
    source_task_id: str
    source_attempt: int
    source_run_id: str | None        # 溯源:run/experiment fingerprint
    first_error_kind: FirstErrorKind # 来源 attribution.kind
    expected_violation: ProcessViolationType
    expected_status: ProcessVerificationStatus
    evidence: tuple[ProcessEvidence, ...]   # 1-minimal 失败片段(结构化,非字符串)
    source_fingerprint: str          # attribution/case 溯源指纹
    original_evidence_count: int     # 最小化前事件数
    minimized_evidence_count: int    # 最小化后事件数
    replay_context: ProcessReplayContext  # verifier 消费的极简字段,自包含
```

`expected_status`:minimize 后对最小片段重新 verify,由目标 violation 的
severity 推出(CRITICAL_VETO / VIOLATION),保证与重放结果一致。

### 入库判定

```python
_SUPPORTED_VIOLATIONS = frozenset({TEST_TAMPERING, TOOL_ERROR_NOT_RECOVERED,
    VALIDATION_MISSING, CONTEXT_REGRESSION, PREMATURE_TERMINATION,
    REPEATED_TOOL_CALL})

def attribution_can_enter_evidence_corpus(
    attribution, *, task, candidate_result, candidate_evidence, verifier=None,
) -> tuple[bool, str]:
    if not attribution.evidence_available: return False, "..."
    if attribution.confidence < 1.0: return False, "..."
    # 以实际 violation 为准(REPEATED_TOOL_CALL 的 kind=UNKNOWN 有歧义)
    verification = verifier.verify(...)
    if not (支持violations ∩ 实际violations): return False, "..."
    return True, ""

def evidence_regression_case_from_attribution(...) -> EvidenceRegressionCase | None:
    # 1) attribution_can_enter_evidence_corpus;2) 目标 violation(优先与
    #    kind 一致,否则按优先级最早);3) minimize;4) 重 verify 推
    #    expected_status;5) 建 case(含 replay_context)
```

### 离线 runner

```python
class EvidenceRegressionCaseStatus(str, Enum): PASS / FAIL / INVALID

class EvidenceRegressionCaseResult(VersionedModel):
    case_id; status; passed: bool
    expected_violation; actual_violations
    expected_status; actual_status
    reason

class EvidenceRegressionCorpusReport(VersionedModel):
    total; passed; failed; invalid
    results: tuple[EvidenceRegressionCaseResult, ...]

def run_evidence_regression_corpus(
    cases: Sequence[EvidenceRegressionCase],
    *,
    verifier: ProcessVerifier | None = None,
) -> EvidenceRegressionCorpusReport:
    # 每条:case 自带 ProcessReplayContext → verifier.verify_case(evidence)
    # 判定:expected_violation 在 actual_violations 中 且 expected_status 匹配 → PASS
    #       否则 FAIL;expected_status/replay 为 EVIDENCE_UNAVAILABLE → INVALID
    # 只验证检测规则本身,不执行任何 Harness 逻辑
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
- minimize 是纯函数、确定性;同输入同输出;保证 1-minimal,不承诺全局最短;
- 不修改 `attribute_first_error`(#149)与 `ProcessVerifier.verify` 行为;
- **重放只验证检测规则本身**:同一 evidence + 同一 verifier 恒得到同一
  结果,与 Harness 改动无关;本层不承担、也不宣称承担 Harness 行为回归;
- 新增符号进 `benchmarks/agent_e2e/__init__.py` 的 `__all__`;
- spec(`.trellis/spec/backend/agent-e2e-evaluation.md`)补充 Regression
  Probe / EvidenceRegressionCase / verify_case 契约与边界。

## 6. 测试要点

- probe:unrecovered error 长轨迹裁成 1-minimal 仍成立;删必要事件后
  不成立;test_tampering 单事件即可;空 evidence False;
- corpus:confidence<1.0 拒绝;evidence_available=False 拒绝;
  PASS→PASS 无 attribution 无法入库;JSON round-trip;
- runner:固定 case 两次运行结果一致(确定性);PASS/FAIL/INVALID 三态。
