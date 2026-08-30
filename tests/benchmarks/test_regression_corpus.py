"""Harness Regression Corpus 单元测试:入库判定 + 生成 + 离线 runner(验收 3/4/5)。"""

from __future__ import annotations

from benchmarks.agent_e2e.evidence import (
    ProcessEvidence,
    TargetScope,
    ToolPhase,
)
from benchmarks.agent_e2e.first_error import (
    FirstErrorAttribution,
    FirstErrorKind,
    attribute_first_error,
)
from benchmarks.agent_e2e.models import (
    AgentRunSummary,
    ResultValidity,
    TaskResult,
    TaskSpec,
    TaskSplit,
    TaskVerdict,
    VerifierOutcome,
    VerifierResult,
)
from benchmarks.agent_e2e.process_verifier import (
    ProcessVerificationStatus,
    ProcessVerifier,
    ProcessViolationType,
)
from benchmarks.agent_e2e.regression_corpus import (
    RegressionCase,
    RegressionCaseResult,
    RegressionCaseStatus,
    RegressionCorpusReport,
    attribution_can_enter_corpus,
    regression_case_from_attribution,
    run_regression_corpus,
)


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="task-1",
        family="bugfix",
        split=TaskSplit.REGRESSION,
        repository="lion",
        base_revision="abcdef0",
        public_prompt="修复公开问题。",
        public_setup=("python -m pip install -e .",),
        public_validation_commands=("python -m pytest -q",),
        verifier_identity="hidden-v1",
        gold_evidence_hash="a" * 64,
        difficulty=2,
        involved_files=("lion_code/meta_agent.py",),
    )


def _result(*, passed: bool, attempt: int = 1) -> TaskResult:
    outcome = VerifierOutcome.PASSED if passed else VerifierOutcome.FAILED
    return TaskResult(
        task_id="task-1",
        attempt=attempt,
        verdict=TaskVerdict.PASSED if passed else TaskVerdict.FAILED,
        validity=ResultValidity.VALID,
        official=True,
        patch_sha256="b" * 64,
        agent_run=AgentRunSummary(
            final_text_digest="c" * 64,
            stop_reason="completed",
            turns=3,
            wall_time_seconds=1,
            input_tokens=10,
            output_tokens=5,
            cache_read_tokens=0,
            cost_usd=0.1,
        ),
        verifier=VerifierResult(
            outcome=outcome,
            command_summary="hidden verifier",
            exit_code=0 if passed else 1,
            output_digest="d" * 64,
        ),
    )


def _fp(value: int) -> str:
    return f"{value:064x}"


def _start(
    sequence: int,
    call_id: str,
    tool: str,
    fp: str,
    *,
    target_scope: TargetScope = TargetScope.SOURCE,
) -> ProcessEvidence:
    return ProcessEvidence(
        sequence=sequence,
        tool_call_id=call_id,
        tool_phase=ToolPhase.START,
        tool_name=tool,
        tool_fingerprint=fp,
        target_scope=target_scope,
    )


def _end(
    sequence: int,
    call_id: str,
    tool: str,
    *,
    error: bool = False,
) -> ProcessEvidence:
    return ProcessEvidence(
        sequence=sequence,
        tool_call_id=call_id,
        tool_phase=ToolPhase.END,
        tool_name=tool,
        is_error=error,
    )


def _baseline_ok() -> tuple[TaskResult, tuple[ProcessEvidence, ...]]:
    return _result(passed=True), (
        _start(1, "c1", "read_file", _fp(1)),
        _end(2, "c1", "read_file"),
        _start(3, "c2", "read_file", _fp(2)),
        _end(4, "c2", "read_file"),
        _start(5, "c3", "edit_file", _fp(3)),
        _end(6, "c3", "edit_file"),
        ProcessEvidence(sequence=7, validation_command=True),
    )


def _candidate_unrecovered() -> tuple[TaskResult, tuple[ProcessEvidence, ...]]:
    return _result(passed=False), (
        _start(1, "c1", "read_file", _fp(1)),
        _end(2, "c1", "read_file"),
        _start(3, "c2", "read_file", _fp(2)),
        _end(4, "c2", "read_file"),
        _start(5, "c3", "edit_file", _fp(9)),
        _end(6, "c3", "edit_file", error=True),
        _start(7, "c4", "edit_file", _fp(9)),
        _end(8, "c4", "edit_file", error=True),
        _start(9, "c5", "edit_file", _fp(9)),
        _end(10, "c5", "edit_file", error=True),
    )


def _build_unrecovered_case() -> RegressionCase:
    task = _task()
    baseline_result, baseline_evidence = _baseline_ok()
    candidate_result, candidate_evidence = _candidate_unrecovered()
    attribution = attribute_first_error(
        task=task,
        candidate_result=candidate_result,
        baseline_result=baseline_result,
        baseline_evidence=baseline_evidence,
        candidate_evidence=candidate_evidence,
    )
    assert attribution is not None
    case = regression_case_from_attribution(
        task=task,
        candidate_result=candidate_result,
        candidate_evidence=candidate_evidence,
        attribution=attribution,
        source_run_id="run-1",
    )
    assert case is not None
    return case


class TestAdmission:
    """验收 3:confidence < 1.0 不允许自动生成 RegressionCase。"""

    def test_low_confidence_attribution_rejected(self) -> None:
        task = _task()
        candidate_result = _result(passed=False)
        candidate_evidence = (_start(1, "c1", "read_file", _fp(1)),)
        attribution = FirstErrorAttribution(
            task_id="task-1",
            attempt=1,
            kind=FirstErrorKind.TOOL_SELECTION,
            confidence=0.6,
            common_prefix_calls=1,
        )
        accepted, reason = attribution_can_enter_corpus(
            attribution,
            task=task,
            candidate_result=candidate_result,
            candidate_evidence=candidate_evidence,
        )
        assert accepted is False
        assert "置信" in reason
        case = regression_case_from_attribution(
            task=task,
            candidate_result=candidate_result,
            candidate_evidence=candidate_evidence,
            attribution=attribution,
        )
        assert case is None

    def test_evidence_unavailable_rejected(self) -> None:
        task = _task()
        candidate_result = _result(passed=False)
        attribution = FirstErrorAttribution(
            task_id="task-1",
            attempt=1,
            kind=FirstErrorKind.UNKNOWN,
            confidence=0.0,
            evidence_available=False,
            common_prefix_calls=0,
            reasons=("旧格式轨迹,无法归因",),
        )
        accepted, reason = attribution_can_enter_corpus(
            attribution,
            task=task,
            candidate_result=candidate_result,
            candidate_evidence=(),
        )
        assert accepted is False
        assert "证据" in reason

    def test_no_deterministic_violation_rejected(self) -> None:
        # confidence 1.0 但 candidate 证据上没有受支持的确定性 violation。
        task = _task()
        candidate_result = _result(passed=False)
        candidate_evidence = (
            _start(1, "c1", "read_file", _fp(1)),
            _end(2, "c1", "read_file"),
        )
        attribution = FirstErrorAttribution(
            task_id="task-1",
            attempt=1,
            kind=FirstErrorKind.UNKNOWN,
            confidence=1.0,
            common_prefix_calls=1,
        )
        accepted, reason = attribution_can_enter_corpus(
            attribution,
            task=task,
            candidate_result=candidate_result,
            candidate_evidence=candidate_evidence,
        )
        assert accepted is False
        assert "violation" in reason


class TestPassPassDivergence:
    """验收 4:PASS→PASS harmless divergence 根本不会进入 corpus。"""

    def test_pass_to_pass_divergence_yields_no_attribution(self) -> None:
        task = _task()
        baseline_result, baseline_evidence = _baseline_ok()
        candidate = _result(passed=True)
        # candidate 换了一条同样有效但参数不同的路径,最终 PASS。
        candidate_evidence = (
            _start(1, "c1", "read_file", _fp(1)),
            _end(2, "c1", "read_file"),
            _start(3, "c2", "read_file", _fp(2)),
            _end(4, "c2", "read_file"),
            _start(5, "c3", "edit_file", _fp(9)),
            _end(6, "c3", "edit_file"),
            ProcessEvidence(sequence=7, validation_command=True),
        )
        attribution = attribute_first_error(
            task=task,
            candidate_result=candidate,
            baseline_result=baseline_result,
            baseline_evidence=baseline_evidence,
            candidate_evidence=candidate_evidence,
        )
        assert attribution is None
        # None attribution 没有可沉淀的对象,corpus 自然为空。
        assert (
            regression_case_from_attribution(
                task=task,
                candidate_result=candidate,
                candidate_evidence=candidate_evidence,
                attribution=FirstErrorAttribution(
                    task_id="task-1",
                    attempt=1,
                    kind=FirstErrorKind.UNKNOWN,
                    confidence=0.0,
                    evidence_available=False,
                    common_prefix_calls=0,
                ),
            )
            is None
        )


class TestGeneration:
    def test_unrecovered_error_full_flow(self) -> None:
        task = _task()
        baseline_result, baseline_evidence = _baseline_ok()
        candidate_result, candidate_evidence = _candidate_unrecovered()
        attribution = attribute_first_error(
            task=task,
            candidate_result=candidate_result,
            baseline_result=baseline_result,
            baseline_evidence=baseline_evidence,
            candidate_evidence=candidate_evidence,
        )
        assert attribution is not None
        case = regression_case_from_attribution(
            task=task,
            candidate_result=candidate_result,
            candidate_evidence=candidate_evidence,
            attribution=attribution,
            source_run_id="run-1",
        )
        assert case is not None
        assert case.expected_violation is ProcessViolationType.TOOL_ERROR_NOT_RECOVERED
        assert case.first_error_kind is FirstErrorKind.ERROR_RECOVERY
        assert case.source_task_id == "task-1"
        assert case.source_attempt == 1
        assert case.source_run_id == "run-1"
        assert len(case.source_fingerprint) == 64
        # 最小化确实发生:片段更短且结构化(不含 #149 的可读 snippet 字段)。
        assert case.minimized_evidence_count < case.original_evidence_count
        assert len(case.evidence) == case.minimized_evidence_count
        # 最小片段仍触发同一 violation,且重放上下文自包含。
        verification = ProcessVerifier().verify_case(
            evidence=case.evidence,
            context=case.replay_context,
            task_id=case.source_task_id,
        )
        assert any(
            violation.violation_type is ProcessViolationType.TOOL_ERROR_NOT_RECOVERED
            for violation in verification.violations
        )
        assert verification.status is case.expected_status

    def test_repeated_tool_call_enters_corpus_despite_unknown_kind(self) -> None:
        # REPEATED_TOOL_CALL 在 first_error 中映射为 kind=UNKNOWN;只要
        # confidence 1.0 且实际 violation 受支持,仍可自动沉淀。
        task = _task()
        baseline_result, baseline_evidence = _baseline_ok()
        candidate = _result(passed=False)
        candidate_evidence = (
            _start(1, "c1", "read_file", _fp(1)),
            _end(2, "c1", "read_file"),
            _start(3, "c2", "read_file", _fp(9)),
            _end(4, "c2", "read_file"),
            _start(5, "c3", "read_file", _fp(9)),
            _end(6, "c3", "read_file"),
            _start(7, "c4", "read_file", _fp(9)),
            _end(8, "c4", "read_file"),
        )
        attribution = attribute_first_error(
            task=task,
            candidate_result=candidate,
            baseline_result=baseline_result,
            baseline_evidence=baseline_evidence,
            candidate_evidence=candidate_evidence,
        )
        assert attribution is not None
        assert attribution.confidence == 1.0
        case = regression_case_from_attribution(
            task=task,
            candidate_result=candidate,
            candidate_evidence=candidate_evidence,
            attribution=attribution,
        )
        assert case is not None
        assert case.expected_violation is ProcessViolationType.REPEATED_TOOL_CALL

    def test_case_round_trip(self) -> None:
        case = _build_unrecovered_case()
        restored = RegressionCase.from_json(case.canonical_json())
        assert restored == case


class TestRunner:
    """验收 5:corpus runner 对固定 case 同输入始终得到同结果。"""

    def test_runner_reports_pass(self) -> None:
        case = _build_unrecovered_case()
        report = run_regression_corpus((case,))
        assert isinstance(report, RegressionCorpusReport)
        assert report.total == 1
        assert report.passed == 1
        assert report.failed == 0
        assert report.invalid == 0
        result = report.results[0]
        assert isinstance(result, RegressionCaseResult)
        assert result.status is RegressionCaseStatus.PASS
        assert result.passed is True
        assert (
            result.expected_violation is ProcessViolationType.TOOL_ERROR_NOT_RECOVERED
        )
        # 最小片段可能同时触发同指纹重复(repeated_tool_call),只要期望
        # violation 在场且 status 一致即为 PASS。
        assert ProcessViolationType.TOOL_ERROR_NOT_RECOVERED in result.actual_violations

    def test_runner_deterministic(self) -> None:
        case = _build_unrecovered_case()
        first = run_regression_corpus((case, case))
        second = run_regression_corpus((case, case))
        assert first == second
        assert first.canonical_json() == second.canonical_json()
        assert first.total == 2
        assert first.passed == 2

    def test_runner_detects_expected_change(self) -> None:
        case = _build_unrecovered_case()
        # 期望改为另一个 violation,重放时应报告 FAIL。
        changed = case.model_copy(
            update={
                "expected_violation": ProcessViolationType.TEST_TAMPERING,
            }
        )
        report = run_regression_corpus((changed,))
        assert report.failed == 1
        result = report.results[0]
        assert result.status is RegressionCaseStatus.FAIL
        assert result.passed is False
        assert ProcessViolationType.TOOL_ERROR_NOT_RECOVERED in result.actual_violations

    def test_runner_invalid_on_unavailable_expected_status(self) -> None:
        case = _build_unrecovered_case()
        malformed = case.model_copy(
            update={
                "expected_status": ProcessVerificationStatus.EVIDENCE_UNAVAILABLE,
            }
        )
        report = run_regression_corpus((malformed,))
        assert report.invalid == 1
        assert report.results[0].status is RegressionCaseStatus.INVALID

    def test_empty_corpus_reports_zero(self) -> None:
        report = run_regression_corpus(())
        assert report.total == 0
        assert report.passed == 0
        assert report.failed == 0
        assert report.invalid == 0
        assert report.results == ()
