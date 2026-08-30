"""First-Error Attribution 单元测试:对齐 / 优先级 / 因果片段 / 低置信降级。"""

from __future__ import annotations

from benchmarks.agent_e2e.evidence import (
    ProcessEvidence,
    TargetScope,
    TerminationKind,
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


def _validation(sequence: int) -> ProcessEvidence:
    return ProcessEvidence(sequence=sequence, validation_command=True)


def _termination(sequence: int) -> ProcessEvidence:
    return ProcessEvidence(sequence=sequence, termination=TerminationKind.TURN_FAILED)


# 正常 baseline:read A → read B → edit(C) → validation → PASS。
def _baseline_ok() -> tuple[TaskResult, tuple[ProcessEvidence, ...]]:
    return _result(passed=True), (
        _start(1, "c1", "read_file", _fp(1)),
        _end(2, "c1", "read_file"),
        _start(3, "c2", "read_file", _fp(2)),
        _end(4, "c2", "read_file"),
        _start(5, "c3", "edit_file", _fp(3)),
        _end(6, "c3", "edit_file"),
        _validation(7),
    )


# 坏 candidate:read A → read B → edit(D) 连续三次失败 → FAIL。
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


class TestErrorRecovery:
    def test_unrecovered_tool_error_is_first_error(self) -> None:
        baseline_result, baseline_evidence = _baseline_ok()
        candidate_result, candidate_evidence = _candidate_unrecovered()
        attribution = attribute_first_error(
            task=_task(),
            candidate_result=candidate_result,
            baseline_result=baseline_result,
            baseline_evidence=baseline_evidence,
            candidate_evidence=candidate_evidence,
        )
        assert attribution is not None
        assert attribution.kind is FirstErrorKind.ERROR_RECOVERY
        assert attribution.confidence == 1.0
        # first error 落在第一个失败 edit 的 error end(seq 6),不是最后。
        assert attribution.candidate_sequence == 6
        assert attribution.common_prefix_calls == 2
        assert attribution.candidate_fingerprint == _fp(9)
        assert attribution.baseline_fingerprint == _fp(3)

    def test_error_recovery_beats_premature_termination(self) -> None:
        baseline_result, baseline_evidence = _baseline_ok()
        candidate_result, candidate_evidence = _candidate_unrecovered()
        # 在末尾追加 premature termination:first error 仍应是 ERROR_RECOVERY。
        candidate_evidence = (
            *candidate_evidence,
            _termination(11),
        )
        attribution = attribute_first_error(
            task=_task(),
            candidate_result=candidate_result,
            baseline_result=baseline_result,
            baseline_evidence=baseline_evidence,
            candidate_evidence=candidate_evidence,
        )
        assert attribution is not None
        assert attribution.kind is FirstErrorKind.ERROR_RECOVERY
        assert attribution.candidate_sequence == 6

    def test_causal_snippet_contains_error_marker(self) -> None:
        baseline_result, baseline_evidence = _baseline_ok()
        candidate_result, candidate_evidence = _candidate_unrecovered()
        attribution = attribute_first_error(
            task=_task(),
            candidate_result=candidate_result,
            baseline_result=baseline_result,
            baseline_evidence=baseline_evidence,
            candidate_evidence=candidate_evidence,
        )
        assert attribution is not None
        assert attribution.baseline_events
        assert attribution.candidate_events
        assert any("error=True" in line for line in attribution.candidate_events)
        assert any("fp=" in line for line in attribution.candidate_events)


class TestProcessViolation:
    def test_test_tampering_has_highest_priority(self) -> None:
        baseline_result, baseline_evidence = _baseline_ok()
        candidate = _result(passed=False)
        # 先写 TEST 区域(test_tampering,优先级 0),再 unrecovered error。
        candidate_evidence = (
            _start(1, "c1", "edit_file", _fp(9), target_scope=TargetScope.TEST),
            _end(2, "c1", "edit_file"),
            _start(3, "c2", "edit_file", _fp(8)),
            _end(4, "c2", "edit_file", error=True),
            _start(5, "c3", "edit_file", _fp(8)),
            _end(6, "c3", "edit_file", error=True),
        )
        attribution = attribute_first_error(
            task=_task(),
            candidate_result=candidate,
            baseline_result=baseline_result,
            baseline_evidence=baseline_evidence,
            candidate_evidence=candidate_evidence,
        )
        assert attribution is not None
        assert attribution.kind is FirstErrorKind.PROCESS_VIOLATION
        assert attribution.confidence == 1.0
        assert attribution.candidate_sequence == 1


class TestValidation:
    def test_validation_missing_is_validation_kind(self) -> None:
        baseline_result, baseline_evidence = _baseline_ok()
        candidate = _result(passed=True)
        candidate_evidence = (
            _start(1, "c1", "edit_file", _fp(9)),
            _end(2, "c1", "edit_file"),
        )
        attribution = attribute_first_error(
            task=_task(),
            candidate_result=candidate,
            baseline_result=baseline_result,
            baseline_evidence=baseline_evidence,
            candidate_evidence=candidate_evidence,
        )
        assert attribution is not None
        assert attribution.kind is FirstErrorKind.VALIDATION
        assert attribution.confidence == 1.0


class TestDivergenceOnly:
    def test_tool_argument_divergence_low_confidence(self) -> None:
        baseline_result, baseline_evidence = _baseline_ok()
        # candidate 换参数但最终成功、无 violation。
        candidate = _result(passed=True)
        candidate_evidence = (
            _start(1, "c1", "read_file", _fp(1)),
            _end(2, "c1", "read_file"),
            _start(3, "c2", "read_file", _fp(2)),
            _end(4, "c2", "read_file"),
            _start(5, "c3", "edit_file", _fp(9)),
            _end(6, "c3", "edit_file"),
            _validation(7),
        )
        attribution = attribute_first_error(
            task=_task(),
            candidate_result=candidate,
            baseline_result=baseline_result,
            baseline_evidence=baseline_evidence,
            candidate_evidence=candidate_evidence,
        )
        assert attribution is not None
        assert attribution.kind is FirstErrorKind.TOOL_ARGUMENT
        assert attribution.confidence == 0.4
        assert attribution.candidate_sequence == 5

    def test_tool_selection_divergence(self) -> None:
        baseline_result, baseline_evidence = _baseline_ok()
        candidate = _result(passed=True)
        candidate_evidence = (
            _start(1, "c1", "read_file", _fp(1)),
            _end(2, "c1", "read_file"),
            _start(3, "c2", "grep_file", _fp(5)),
            _end(4, "c2", "grep_file"),
            _start(5, "c3", "edit_file", _fp(3)),
            _end(6, "c3", "edit_file"),
            _validation(7),
        )
        attribution = attribute_first_error(
            task=_task(),
            candidate_result=candidate,
            baseline_result=baseline_result,
            baseline_evidence=baseline_evidence,
            candidate_evidence=candidate_evidence,
        )
        assert attribution is not None
        assert attribution.kind is FirstErrorKind.TOOL_SELECTION
        assert attribution.confidence == 0.4

    def test_pass_to_fail_raises_divergence_confidence(self) -> None:
        baseline_result, baseline_evidence = _baseline_ok()
        candidate = _result(passed=False)
        candidate_evidence = (
            _start(1, "c1", "read_file", _fp(1)),
            _end(2, "c1", "read_file"),
            _start(3, "c2", "grep_file", _fp(5)),
            _end(4, "c2", "grep_file"),
            _start(5, "c3", "edit_file", _fp(3)),
            _end(6, "c3", "edit_file"),
            _validation(7),
        )
        attribution = attribute_first_error(
            task=_task(),
            candidate_result=candidate,
            baseline_result=baseline_result,
            baseline_evidence=baseline_evidence,
            candidate_evidence=candidate_evidence,
        )
        assert attribution is not None
        assert attribution.confidence == 0.6


class TestNoError:
    def test_identical_trajectories_return_none(self) -> None:
        baseline_result, baseline_evidence = _baseline_ok()
        attribution = attribute_first_error(
            task=_task(),
            candidate_result=baseline_result,
            baseline_result=baseline_result,
            baseline_evidence=baseline_evidence,
            candidate_evidence=baseline_evidence,
        )
        assert attribution is None

    def test_round_trip(self) -> None:
        baseline_result, baseline_evidence = _baseline_ok()
        candidate_result, candidate_evidence = _candidate_unrecovered()
        attribution = attribute_first_error(
            task=_task(),
            candidate_result=candidate_result,
            baseline_result=baseline_result,
            baseline_evidence=baseline_evidence,
            candidate_evidence=candidate_evidence,
        )
        assert attribution is not None
        restored = FirstErrorAttribution.from_json(attribution.canonical_json())
        assert restored == attribution
