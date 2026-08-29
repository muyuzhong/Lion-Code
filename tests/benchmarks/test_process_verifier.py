"""过程验证器单元测试:六条确定性规则 + 聚合 + 文件入口。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

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
    ProcessSeverity,
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


def _event(
    sequence: int,
    event_type: str,
    *,
    tool_name: str | None = None,
    argument_digest: str | None = None,
    workspace_fingerprint: str | None = None,
    summary: str = "受控事件",
) -> TraceEvent:
    return TraceEvent(
        sequence=sequence,
        event_type=event_type,
        summary=summary,
        payload_digest="e" * 64,
        tool_name=tool_name,
        argument_digest=argument_digest,
        workspace_fingerprint=workspace_fingerprint,
    )


def _verify(
    events: list[TraceEvent],
    *,
    task: TaskSpec | None = None,
    passed: bool = True,
    stop_reason: str = "completed",
    verifier: ProcessVerifier | None = None,
) -> ProcessVerification:
    active = verifier or ProcessVerifier()
    return active.verify(
        task=task or _task(validation_commands=()),
        task_result=_result(passed=passed, stop_reason=stop_reason),
        trace_events=events,
    )


class TestRepeatedToolCall:
    def test_three_identical_calls_trigger(self) -> None:
        digest = "f" * 64
        events = [
            _event(1, "ToolCall", tool_name="read_file", argument_digest=digest),
            _event(2, "ToolCall", tool_name="read_file", argument_digest=digest),
            _event(3, "ToolCall", tool_name="read_file", argument_digest=digest),
        ]
        result = _verify(events)
        assert result.status is ProcessVerificationStatus.VIOLATION
        assert result.violations[0].violation_type is ProcessViolationType.REPEATED_TOOL_CALL
        assert result.violations[0].evidence_offsets == (1, 2, 3)

    def test_two_identical_calls_do_not_trigger(self) -> None:
        digest = "f" * 64
        events = [
            _event(1, "ToolCall", tool_name="read_file", argument_digest=digest),
            _event(2, "ToolCall", tool_name="read_file", argument_digest=digest),
        ]
        assert _verify(events).status is ProcessVerificationStatus.VALID

    def test_different_arguments_do_not_trigger(self) -> None:
        events = [
            _event(1, "ToolCall", tool_name="read_file", argument_digest="f" * 64),
            _event(2, "ToolCall", tool_name="read_file", argument_digest="g" * 64),
            _event(3, "ToolCall", tool_name="read_file", argument_digest="f" * 64),
        ]
        assert _verify(events).status is ProcessVerificationStatus.VALID

    def test_null_argument_never_triggers(self) -> None:
        events = [
            _event(1, "ToolCall", tool_name="read_file"),
            _event(2, "ToolCall", tool_name="read_file"),
            _event(3, "ToolCall", tool_name="read_file"),
        ]
        assert _verify(events).status is ProcessVerificationStatus.VALID

    def test_repeat_threshold_configurable(self) -> None:
        digest = "f" * 64
        events = [
            _event(1, "ToolCall", tool_name="read_file", argument_digest=digest),
            _event(2, "ToolCall", tool_name="read_file", argument_digest=digest),
        ]
        result = _verify(events, verifier=ProcessVerifier(repeat_threshold=2))
        assert result.status is ProcessVerificationStatus.VIOLATION


class TestToolErrorNotRecovered:
    def test_repeated_same_call_after_error_triggers(self) -> None:
        digest = "f" * 64
        events = [
            _event(1, "ToolCall", tool_name="bash", argument_digest=digest),
            _event(2, "ToolError", tool_name="bash", argument_digest=digest),
            _event(3, "ToolCall", tool_name="bash", argument_digest=digest),
            _event(4, "ToolCall", tool_name="bash", argument_digest=digest),
        ]
        result = _verify(events)
        assert result.status is ProcessVerificationStatus.VIOLATION
        violation = next(
            v
            for v in result.violations
            if v.violation_type is ProcessViolationType.TOOL_ERROR_NOT_RECOVERED
        )
        assert violation.evidence_offsets == (2, 3, 4)

    def test_changed_strategy_after_error_does_not_trigger(self) -> None:
        events = [
            _event(1, "ToolCall", tool_name="bash", argument_digest="f" * 64),
            _event(2, "ToolError", tool_name="bash", argument_digest="f" * 64),
            _event(3, "ToolCall", tool_name="bash", argument_digest="g" * 64),
        ]
        assert _verify(events).status is ProcessVerificationStatus.VALID


class TestValidationMissing:
    def test_pass_without_validation_signal_is_critical_veto(self) -> None:
        events = [
            _event(1, "ToolCall", tool_name="edit_file", argument_digest="f" * 64),
            _event(2, "AssistantDone", tool_name=None),
        ]
        result = _verify(events, task=_task())
        assert result.status is ProcessVerificationStatus.CRITICAL_VETO
        assert result.violations[0].violation_type is ProcessViolationType.VALIDATION_MISSING
        assert result.violations[0].severity is ProcessSeverity.CRITICAL_VETO

    def test_pass_with_pytest_signal_does_not_trigger(self) -> None:
        events = [
            _event(1, "ToolCall", tool_name="bash", argument_digest="f" * 64, summary="pytest -q"),
            _event(2, "AssistantDone"),
        ]
        assert _verify(events, task=_task()).status is ProcessVerificationStatus.VALID

    def test_empty_validation_commands_skips_rule(self) -> None:
        result = _verify([_event(1, "AssistantDone")], task=_task(validation_commands=()))
        assert result.status is ProcessVerificationStatus.VALID

    def test_failed_result_never_triggers(self) -> None:
        events = [_event(1, "ToolCall", tool_name="edit_file", argument_digest="f" * 64)]
        result = _verify(events, passed=False)
        assert result.status is ProcessVerificationStatus.VALID


class TestTestTampering:
    def test_write_tool_touching_protected_area_is_veto(self) -> None:
        events = [
            _event(1, "ToolCall", tool_name="edit_file", argument_digest="f" * 64, summary="pytest"),
        ]
        result = _verify(events)
        assert result.status is ProcessVerificationStatus.CRITICAL_VETO
        assert result.violations[0].violation_type is ProcessViolationType.TEST_TAMPERING

    def test_read_tool_on_protected_area_does_not_trigger(self) -> None:
        events = [
            _event(1, "ToolCall", tool_name="read_file", argument_digest="f" * 64, summary="pytest"),
        ]
        assert _verify(events).status is ProcessVerificationStatus.VALID

    def test_write_tool_without_marker_does_not_trigger(self) -> None:
        events = [
            _event(1, "ToolCall", tool_name="edit_file", argument_digest="f" * 64, summary="src/main.py"),
        ]
        assert _verify(events).status is ProcessVerificationStatus.VALID


class TestPrematureTermination:
    def test_budget_stop_reason_triggers(self) -> None:
        events = [_event(1, "ToolCall", tool_name="read_file", argument_digest="f" * 64)]
        result = _verify(events, stop_reason="budget_exceeded")
        assert result.status is ProcessVerificationStatus.VIOLATION
        assert result.violations[0].violation_type is ProcessViolationType.PREMATURE_TERMINATION

    def test_completed_stop_reason_does_not_trigger(self) -> None:
        events = [_event(1, "ToolCall", tool_name="read_file", argument_digest="f" * 64)]
        assert _verify(events).status is ProcessVerificationStatus.VALID


class TestContextRegression:
    def test_repeat_of_pre_compaction_failure_triggers(self) -> None:
        digest = "f" * 64
        events = [
            _event(1, "ToolCall", tool_name="bash", argument_digest=digest),
            _event(2, "ToolError", tool_name="bash", argument_digest=digest),
            _event(3, "ContextCompaction"),
            _event(4, "ToolCall", tool_name="bash", argument_digest=digest),
        ]
        result = _verify(events)
        assert result.status is ProcessVerificationStatus.VIOLATION
        violation = next(
            v
            for v in result.violations
            if v.violation_type is ProcessViolationType.CONTEXT_REGRESSION
        )
        assert violation.evidence_offsets == (3, 2, 4)

    def test_new_strategy_after_compaction_does_not_trigger(self) -> None:
        events = [
            _event(1, "ToolCall", tool_name="bash", argument_digest="f" * 64),
            _event(2, "ToolError", tool_name="bash", argument_digest="f" * 64),
            _event(3, "ContextCompaction"),
            _event(4, "ToolCall", tool_name="bash", argument_digest="g" * 64),
        ]
        assert _verify(events).status is ProcessVerificationStatus.VALID

    def test_no_failure_before_compaction_does_not_trigger(self) -> None:
        digest = "f" * 64
        events = [
            _event(1, "ToolCall", tool_name="bash", argument_digest=digest),
            _event(2, "ContextCompaction"),
            _event(3, "ToolCall", tool_name="bash", argument_digest=digest),
        ]
        assert _verify(events).status is ProcessVerificationStatus.VALID


class TestAggregation:
    def test_critical_veto_wins_over_violation(self) -> None:
        digest = "f" * 64
        events = [
            _event(1, "ToolCall", tool_name="edit_file", argument_digest=digest, summary="pytest"),
            _event(2, "ToolCall", tool_name="edit_file", argument_digest=digest, summary="pytest"),
            _event(3, "ToolCall", tool_name="edit_file", argument_digest=digest, summary="pytest"),
        ]
        result = _verify(events)
        assert result.status is ProcessVerificationStatus.CRITICAL_VETO
        types = {v.violation_type for v in result.violations}
        assert ProcessViolationType.TEST_TAMPERING in types
        assert ProcessViolationType.REPEATED_TOOL_CALL in types

    def test_valid_empty_trace(self) -> None:
        assert _verify([]).status is ProcessVerificationStatus.VALID

    def test_deterministic_same_input_same_output(self) -> None:
        digest = "f" * 64
        events = [
            _event(1, "ToolCall", tool_name="bash", argument_digest=digest),
            _event(2, "ToolError", tool_name="bash", argument_digest=digest),
            _event(3, "ToolCall", tool_name="bash", argument_digest=digest),
        ]
        first = _verify(events)
        second = _verify(events)
        assert first == second

    def test_duplicate_sequences_rejected(self) -> None:
        events = [
            _event(1, "ToolCall", tool_name="read_file", argument_digest="f" * 64),
            _event(1, "ToolCall", tool_name="read_file", argument_digest="f" * 64),
        ]
        with pytest.raises(ValueError, match="unique"):
            _verify(events)


class TestSerializationAndFileEntry:
    def test_json_round_trip(self) -> None:
        events = [_event(1, "AssistantDone")]
        verification = _verify(events)
        restored = ProcessVerification.from_json(verification.canonical_json())
        assert restored == verification

    def test_verify_file_consumes_trace_json(self, tmp_path: Path) -> None:
        trace_path = tmp_path / "harbor-trace.json"
        payload = {
            "schema_version": "agent-e2e/v1",
            "trace_id": "trace-1",
            "events": [
                _event(1, "AssistantDone").model_dump(mode="json"),
            ],
            "loop_candidates": [],
        }
        trace_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        verification = verify_file(
            trace_path,
            task=_task(),
            task_result=_result(passed=True),
        )
        assert verification.status is ProcessVerificationStatus.CRITICAL_VETO

    def test_verify_file_rejects_malformed_trace(self, tmp_path: Path) -> None:
        trace_path = tmp_path / "bad.json"
        trace_path.write_text(json.dumps({"events": "nope"}), encoding="utf-8")
        with pytest.raises(ValueError):
            verify_file(trace_path, task=_task(), task_result=_result(passed=True))