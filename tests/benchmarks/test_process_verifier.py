"""ProcessVerifier V2 单元测试:六条证据规则 + 聚合 + 旧数据降级。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.agent_e2e.evidence import (
    ProcessEvidence,
    ProcessEvidenceProjector,
    TargetScope,
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
    ProcessVerification,
    ProcessVerificationStatus,
    ProcessVerifier,
    ProcessViolationType,
    verify_file,
)
from benchmarks.agent_e2e.trace import TraceEvent


def _task(*, validation_commands: tuple[str, ...] = ("python -m pytest -q",)) -> TaskSpec:
    return TaskSpec(
        task_id="task-1",
        family="bugfix",
        split=TaskSplit.REGRESSION,
        repository="lion",
        base_revision="abcdef0",
        public_prompt="修复公开问题。",
        public_setup=("python -m pip install -e .",),
        public_validation_commands=validation_commands,
        verifier_identity="hidden-v1",
        gold_evidence_hash="a" * 64,
        difficulty=2,
        involved_files=("lion_code/meta_agent.py",),
    )


def _result(
    *,
    passed: bool,
    stop_reason: str = "completed",
    attempt: int = 1,
) -> TaskResult:
    outcome = VerifierOutcome.PASSED if passed else VerifierOutcome.FAILED
    verdict = TaskVerdict.PASSED if passed else TaskVerdict.FAILED
    return TaskResult(
        task_id="task-1",
        attempt=attempt,
        verdict=verdict,
        validity=ResultValidity.VALID,
        official=True,
        patch_sha256="b" * 64,
        agent_run=AgentRunSummary(
            final_text_digest="c" * 64,
            stop_reason=stop_reason,
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


def _event(sequence: int, event_type: str) -> TraceEvent:
    return TraceEvent(
        sequence=sequence,
        event_type=event_type,
        summary="受控事件",
        payload_digest="e" * 64,
    )


def _evidence(
    sequence: int,
    *,
    tool_call_id: str | None = None,
    tool_phase: object | None = None,
    tool_name: str | None = None,
    tool_fingerprint: str | None = None,
    is_error: bool | None = None,
    target_scope: TargetScope = TargetScope.OTHER,
    validation_command: bool = False,
    compaction: object | None = None,
    termination: object | None = None,
) -> ProcessEvidence:
    from benchmarks.agent_e2e.evidence import (
        CompactionState,
        TerminationKind,
    )

    compaction_value = CompactionState(compaction) if compaction else None
    termination_value = TerminationKind(termination) if termination else None
    return ProcessEvidence(
        sequence=sequence,
        tool_call_id=tool_call_id,
        tool_phase=tool_phase,
        tool_name=tool_name,
        tool_fingerprint=tool_fingerprint,
        is_error=is_error,
        target_scope=target_scope,
        validation_command=validation_command,
        compaction=compaction_value,
        termination=termination_value,
    )


def _verify(
    evidence: list[ProcessEvidence],
    *,
    task: TaskSpec | None = None,
    passed: bool = True,
    stop_reason: str = "completed",
    verifier: ProcessVerifier | None = None,
) -> ProcessVerification:
    active = verifier or ProcessVerifier()
    return active.verify(
        task=task or _task(),
        task_result=_result(passed=passed, stop_reason=stop_reason),
        trace_events=(),
        evidence=evidence,
    )


def _tool_fingerprint(tool_name: str) -> str:
    import hashlib

    return hashlib.sha256(tool_name.encode("utf-8")).hexdigest()


LIC = "f" * 64


class TestRepeatedToolCall:
    def test_single_call_lifecycle_does_not_trigger(self) -> None:
        # 一次调用的 start/update/end 生命周期不得误判为重复。
        evidence = [
            _evidence(1, tool_call_id="call-1", tool_phase="start", tool_fingerprint=LIC),
            _evidence(2, tool_call_id="call-1", tool_phase="update", tool_fingerprint=LIC),
            _evidence(3, tool_call_id="call-1", tool_phase="end", tool_fingerprint=LIC),
        ]
        assert _verify(evidence, task=_task(validation_commands=())).status is ProcessVerificationStatus.VALID

    def test_three_identical_calls_trigger(self) -> None:
        evidence = [
            _evidence(1, tool_call_id="call-1", tool_phase="end", tool_fingerprint=LIC),
            _evidence(2, tool_call_id="call-2", tool_phase="end", tool_fingerprint=LIC),
            _evidence(3, tool_call_id="call-3", tool_phase="end", tool_fingerprint=LIC),
        ]
        result = _verify(evidence, task=_task(validation_commands=()))
        assert result.status is ProcessVerificationStatus.VIOLATION
        assert result.violations[0].violation_type is ProcessViolationType.REPEATED_TOOL_CALL
        assert result.violations[0].evidence_offsets == (1, 2, 3)

    def test_interleaved_different_calls_do_not_trigger(self) -> None:
        evidence = [
            _evidence(1, tool_call_id="call-1", tool_phase="end", tool_fingerprint=LIC),
            _evidence(2, tool_call_id="call-2", tool_phase="end", tool_fingerprint="g" * 64),
            _evidence(3, tool_call_id="call-3", tool_phase="end", tool_fingerprint=LIC),
        ]
        assert _verify(evidence, task=_task(validation_commands=())).status is ProcessVerificationStatus.VALID

    def test_repeat_threshold_configurable(self) -> None:
        evidence = [
            _evidence(1, tool_call_id="call-1", tool_phase="end", tool_fingerprint=LIC),
            _evidence(2, tool_call_id="call-2", tool_phase="end", tool_fingerprint=LIC),
        ]
        result = _verify(
            evidence,
            task=_task(validation_commands=()),
            verifier=ProcessVerifier(repeat_threshold=2),
        )
        assert result.status is ProcessVerificationStatus.VIOLATION


class TestToolErrorNotRecovered:
    def test_repeated_same_call_after_error_triggers(self) -> None:
        evidence = [
            _evidence(1, tool_call_id="call-1", tool_phase="end", tool_fingerprint=LIC, is_error=True),
            _evidence(2, tool_call_id="call-2", tool_phase="end", tool_fingerprint=LIC),
            _evidence(3, tool_call_id="call-3", tool_phase="end", tool_fingerprint=LIC),
        ]
        result = _verify(evidence, task=_task(validation_commands=()))
        assert result.status is ProcessVerificationStatus.VIOLATION
        violation = next(
            v
            for v in result.violations
            if v.violation_type is ProcessViolationType.TOOL_ERROR_NOT_RECOVERED
        )
        assert violation.evidence_offsets == (1, 2, 3)

    def test_changed_strategy_after_error_does_not_trigger(self) -> None:
        evidence = [
            _evidence(1, tool_call_id="call-1", tool_phase="end", tool_fingerprint=LIC, is_error=True),
            _evidence(2, tool_call_id="call-2", tool_phase="end", tool_fingerprint="g" * 64),
        ]
        assert _verify(evidence, task=_task(validation_commands=())).status is ProcessVerificationStatus.VALID

    def test_clean_end_without_error_never_triggers(self) -> None:
        evidence = [
            _evidence(1, tool_call_id="call-1", tool_phase="end", tool_fingerprint=LIC, is_error=False),
            _evidence(2, tool_call_id="call-2", tool_phase="end", tool_fingerprint=LIC),
        ]
        assert _verify(evidence, task=_task(validation_commands=())).status is ProcessVerificationStatus.VALID


class TestValidationMissing:
    def test_pass_without_validation_signal_is_critical_veto(self) -> None:
        evidence = [
            _evidence(1, tool_call_id="call-1", tool_phase="end", tool_name="edit_file"),
        ]
        result = _verify(evidence)
        assert result.status is ProcessVerificationStatus.CRITICAL_VETO
        assert result.violations[0].violation_type is ProcessViolationType.VALIDATION_MISSING

    def test_pass_with_validation_signal_does_not_trigger(self) -> None:
        evidence = [
            _evidence(1, tool_call_id="call-1", tool_phase="end", validation_command=True),
        ]
        assert _verify(evidence).status is ProcessVerificationStatus.VALID

    def test_empty_validation_commands_skips_rule(self) -> None:
        evidence = [_evidence(1, tool_call_id="call-1", tool_phase="end")]
        result = _verify(evidence, task=_task(validation_commands=()))
        assert result.status is ProcessVerificationStatus.VALID

    def test_failed_result_never_triggers(self) -> None:
        evidence = [_evidence(1, tool_call_id="call-1", tool_phase="end")]
        result = _verify(evidence, passed=False)
        assert result.status is ProcessVerificationStatus.VALID


class TestTestTampering:
    def test_write_test_file_is_veto(self) -> None:
        evidence = [
            _evidence(
                1,
                tool_call_id="call-1",
                tool_phase="end",
                tool_name="edit_file",
                target_scope=TargetScope.TEST,
            ),
        ]
        result = _verify(evidence, task=_task(validation_commands=()))
        assert result.status is ProcessVerificationStatus.CRITICAL_VETO
        assert result.violations[0].violation_type is ProcessViolationType.TEST_TAMPERING

    def test_write_verifier_file_is_veto(self) -> None:
        evidence = [
            _evidence(
                1,
                tool_call_id="call-1",
                tool_phase="end",
                tool_name="write_file",
                target_scope=TargetScope.VERIFIER,
            ),
        ]
        result = _verify(evidence, task=_task(validation_commands=()))
        assert result.status is ProcessVerificationStatus.CRITICAL_VETO

    def test_read_tool_on_test_file_does_not_trigger(self) -> None:
        evidence = [
            _evidence(
                1,
                tool_call_id="call-1",
                tool_phase="end",
                tool_name="read_file",
                target_scope=TargetScope.TEST,
            ),
        ]
        assert _verify(evidence, task=_task(validation_commands=())).status is ProcessVerificationStatus.VALID

    def test_write_source_file_does_not_trigger(self) -> None:
        evidence = [
            _evidence(
                1,
                tool_call_id="call-1",
                tool_phase="end",
                tool_name="edit_file",
                target_scope=TargetScope.SOURCE,
            ),
        ]
        assert _verify(evidence, task=_task(validation_commands=())).status is ProcessVerificationStatus.VALID


class TestPrematureTermination:
    def test_cancelled_termination_triggers(self) -> None:
        from benchmarks.agent_e2e.evidence import TerminationKind

        evidence = [
            _evidence(1, termination=TerminationKind.CANCELLED.value),
        ]
        result = _verify(evidence, task=_task(validation_commands=()))
        assert result.status is ProcessVerificationStatus.VIOLATION
        assert result.violations[0].violation_type is ProcessViolationType.PREMATURE_TERMINATION

    def test_turn_failed_termination_triggers(self) -> None:
        from benchmarks.agent_e2e.evidence import TerminationKind

        evidence = [
            _evidence(1, termination=TerminationKind.TURN_FAILED.value),
        ]
        result = _verify(evidence, task=_task(validation_commands=()))
        assert result.status is ProcessVerificationStatus.VIOLATION

    def test_budget_stop_reason_triggers(self) -> None:
        evidence = [_evidence(1, tool_call_id="call-1", tool_phase="end")]
        result = _verify(
            evidence,
            task=_task(validation_commands=()),
            stop_reason="budget_exceeded",
        )
        assert result.status is ProcessVerificationStatus.VIOLATION

    def test_completed_stop_reason_does_not_trigger(self) -> None:
        evidence = [_evidence(1, tool_call_id="call-1", tool_phase="end")]
        assert _verify(evidence, task=_task(validation_commands=())).status is ProcessVerificationStatus.VALID


class TestContextRegression:
    def test_repeat_of_pre_compaction_failure_triggers(self) -> None:
        from benchmarks.agent_e2e.evidence import CompactionState

        evidence = [
            _evidence(1, tool_call_id="call-1", tool_phase="end", tool_fingerprint=LIC, is_error=True),
            _evidence(2, compaction=CompactionState.COMPLETED.value),
            _evidence(3, tool_call_id="call-2", tool_phase="end", tool_fingerprint=LIC),
        ]
        result = _verify(evidence, task=_task(validation_commands=()))
        assert result.status is ProcessVerificationStatus.VIOLATION
        violation = next(
            v
            for v in result.violations
            if v.violation_type is ProcessViolationType.CONTEXT_REGRESSION
        )
        assert violation.evidence_offsets == (2, 1, 3)

    def test_new_strategy_after_compaction_does_not_trigger(self) -> None:
        from benchmarks.agent_e2e.evidence import CompactionState

        evidence = [
            _evidence(1, tool_call_id="call-1", tool_phase="end", tool_fingerprint=LIC, is_error=True),
            _evidence(2, compaction=CompactionState.COMPLETED.value),
            _evidence(3, tool_call_id="call-2", tool_phase="end", tool_fingerprint="g" * 64),
        ]
        assert _verify(evidence, task=_task(validation_commands=())).status is ProcessVerificationStatus.VALID

    def test_no_failure_before_compaction_does_not_trigger(self) -> None:
        from benchmarks.agent_e2e.evidence import CompactionState

        evidence = [
            _evidence(1, tool_call_id="call-1", tool_phase="end", tool_fingerprint=LIC),
            _evidence(2, compaction=CompactionState.COMPLETED.value),
            _evidence(3, tool_call_id="call-2", tool_phase="end", tool_fingerprint=LIC),
        ]
        assert _verify(evidence, task=_task(validation_commands=())).status is ProcessVerificationStatus.VALID


class TestAggregationAndDegradation:
    def test_critical_veto_wins_over_violation(self) -> None:
        evidence = [
            _evidence(
                1,
                tool_call_id="call-1",
                tool_phase="end",
                tool_name="edit_file",
                target_scope=TargetScope.TEST,
            ),
            _evidence(2, tool_call_id="call-2", tool_phase="end", tool_fingerprint=LIC),
            _evidence(3, tool_call_id="call-3", tool_phase="end", tool_fingerprint=LIC),
            _evidence(4, tool_call_id="call-4", tool_phase="end", tool_fingerprint=LIC),
        ]
        result = _verify(evidence, task=_task(validation_commands=()))
        assert result.status is ProcessVerificationStatus.CRITICAL_VETO
        types = {v.violation_type for v in result.violations}
        assert ProcessViolationType.TEST_TAMPERING in types
        assert ProcessViolationType.REPEATED_TOOL_CALL in types

    def test_valid_trace_with_validation_signal(self) -> None:
        evidence = [
            _evidence(1, tool_call_id="call-1", tool_phase="end", validation_command=True),
            _evidence(2, tool_call_id="call-2", tool_phase="end", tool_fingerprint="g" * 64),
        ]
        assert _verify(evidence).status is ProcessVerificationStatus.VALID

    def test_empty_evidence_is_evidence_unavailable(self) -> None:
        result = _verify(
            [],
            task=_task(validation_commands=()),
        )
        assert result.status is ProcessVerificationStatus.EVIDENCE_UNAVAILABLE
        assert "degraded_reason" in result.extensions

    def test_evidence_unavailable_never_guesses(self) -> None:
        # 即使 stop_reason 看起来异常,无证据时也绝不判 violation。
        result = _verify(
            [],
            task=_task(validation_commands=()),
            stop_reason="budget_exceeded",
        )
        assert result.status is ProcessVerificationStatus.EVIDENCE_UNAVAILABLE

    def test_deterministic_same_input_same_output(self) -> None:
        evidence = [
            _evidence(1, tool_call_id="call-1", tool_phase="end", tool_fingerprint=LIC, is_error=True),
            _evidence(2, tool_call_id="call-2", tool_phase="end", tool_fingerprint=LIC),
        ]
        first = _verify(evidence, task=_task(validation_commands=()))
        second = _verify(evidence, task=_task(validation_commands=()))
        assert first == second


class TestSerializationAndFileEntry:
    def test_json_round_trip(self) -> None:
        verification = _verify(
            [_evidence(1, tool_call_id="call-1", tool_phase="end")],
            task=_task(validation_commands=()),
        )
        restored = ProcessVerification.from_json(verification.canonical_json())
        assert restored == verification

    def test_verify_file_consumes_evidence_array(self, tmp_path: Path) -> None:
        trace_path = tmp_path / "harbor-trace.json"
        payload = {
            "schema_version": "agent-e2e/v1",
            "trace_id": "trace-1",
            "events": [_event(1, "tool_execution_end").model_dump(mode="json")],
            "evidence": [
                _evidence(1, tool_call_id="call-1", tool_phase="end").model_dump(mode="json")
            ],
            "loop_candidates": [],
        }
        trace_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        verification = verify_file(
            trace_path,
            task=_task(),
            task_result=_result(passed=True),
        )
        assert verification.status is ProcessVerificationStatus.CRITICAL_VETO  # validation missing

    def test_verify_file_legacy_trace_degrades(self, tmp_path: Path) -> None:
        trace_path = tmp_path / "legacy.json"
        payload = {
            "schema_version": "agent-e2e/v1",
            "trace_id": "trace-legacy",
            "events": [_event(1, "tool_execution_end").model_dump(mode="json")],
            "loop_candidates": [],
        }
        trace_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        verification = verify_file(
            trace_path,
            task=_task(),
            task_result=_result(passed=True),
        )
        assert verification.status is ProcessVerificationStatus.EVIDENCE_UNAVAILABLE

    def test_verify_file_rejects_malformed_trace(self, tmp_path: Path) -> None:
        trace_path = tmp_path / "bad.json"
        trace_path.write_text(json.dumps({"events": "nope"}), encoding="utf-8")
        with pytest.raises(ValueError):
            verify_file(trace_path, task=_task(), task_result=_result(passed=True))


class TestRealProjectionIntegration:
    """从 typed event 走真实投影链路,验证 V2 规则在真实语义上工作。"""

    def test_tampering_detected_via_projection(self) -> None:
        from lion_code.core.events import ToolExecutionEndEvent, ToolExecutionStartEvent

        recorder = ProcessEvidenceProjector()
        recorder2 = [recorder.project(
            ToolExecutionStartEvent(
                tool_call_id="c1", tool_name="edit_file", args={"file_path": "tests/test_x.py"}
            ),
            sequence=1,
        ), recorder.project(
            ToolExecutionEndEvent(tool_call_id="c1", tool_name="edit_file", result={}, is_error=False),
            sequence=2,
        )]
        evidence = [item for item in recorder2 if item is not None]
        assert evidence
        result = _verify(evidence, task=_task(validation_commands=()))
        assert result.status is ProcessVerificationStatus.CRITICAL_VETO
        assert any(
            v.violation_type is ProcessViolationType.TEST_TAMPERING
            for v in result.violations
        )

    def test_validation_signal_via_projection(self) -> None:
        from lion_code.core.events import ToolExecutionEndEvent, ToolExecutionStartEvent

        projector = ProcessEvidenceProjector(validation_commands=("python -m pytest -q",))
        evidence = [
            projector.project(
                ToolExecutionStartEvent(
                    tool_call_id="c1", tool_name="run_shell", args={"command": "pytest -q"}
                ),
                sequence=1,
            ),
            projector.project(
                ToolExecutionEndEvent(tool_call_id="c1", tool_name="run_shell", result={}, is_error=False),
                sequence=2,
            ),
        ]
        evidence = [item for item in evidence if item is not None]
        result = _verify(evidence)
        assert result.status is ProcessVerificationStatus.VALID
        assert any(item.validation_command for item in evidence)