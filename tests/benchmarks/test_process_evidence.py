"""过程证据投影单元测试:typed event → ProcessEvidence 的语义化投影。"""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.agent_e2e.evidence import (
    CompactionState,
    PathScopeRules,
    ProcessEvidence,
    ProcessEvidenceProjector,
    TargetScope,
    TerminationKind,
    ToolPhase,
)
from benchmarks.agent_e2e.trace import TraceRecorder
from lion_code.core.events import (
    CancelledEvent,
    CompactionCompletedEvent,
    CompactionStartedEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    TurnFailedEvent,
)
from lion_code.core.messages import UserMessage


def _start(
    tool_call_id: str = "call-1",
    tool_name: str = "run_shell",
    args: dict | None = None,
) -> ToolExecutionStartEvent:
    return ToolExecutionStartEvent(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        args=args or {"command": "pytest -q"},
    )


def _end(
    tool_call_id: str = "call-1",
    tool_name: str = "run_shell",
    is_error: bool = False,
) -> ToolExecutionEndEvent:
    return ToolExecutionEndEvent(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        result={},
        is_error=is_error,
    )


class TestToolEvidence:
    def test_start_evidence_has_call_id_and_phase(self) -> None:
        evidence = ProcessEvidenceProjector().project(_start(), sequence=3)
        assert evidence is not None
        assert evidence.sequence == 3
        assert evidence.tool_call_id == "call-1"
        assert evidence.tool_phase is ToolPhase.START
        assert evidence.tool_name == "run_shell"
        assert evidence.is_error is None

    def test_end_evidence_has_is_error(self) -> None:
        evidence = ProcessEvidenceProjector().project(
            _end(is_error=True), sequence=4
        )
        assert evidence is not None
        assert evidence.tool_phase is ToolPhase.END
        assert evidence.is_error is True

    def test_tool_fingerprint_stable(self) -> None:
        projector = ProcessEvidenceProjector()
        first = projector.project(_start(), sequence=1)
        second = projector.project(_start(), sequence=2)
        assert first is not None and second is not None
        assert first.tool_fingerprint == second.tool_fingerprint


class TestPathScope:
    def test_source_path(self) -> None:
        evidence = ProcessEvidenceProjector().project(
            _start(tool_name="edit_file", args={"file_path": "lion_code/meta_agent.py"}),
            sequence=1,
        )
        assert evidence is not None
        assert evidence.target_scope is TargetScope.SOURCE
        assert evidence.path_digest is not None

    def test_test_path(self) -> None:
        evidence = ProcessEvidenceProjector().project(
            _start(tool_name="edit_file", args={"file_path": "tests/test_agent.py"}),
            sequence=1,
        )
        assert evidence is not None
        assert evidence.target_scope is TargetScope.TEST

    def test_verifier_path(self) -> None:
        evidence = ProcessEvidenceProjector().project(
            _start(tool_name="edit_file", args={"file_path": "hidden/verifier.py"}),
            sequence=1,
        )
        assert evidence is not None
        assert evidence.target_scope is TargetScope.VERIFIER

    def test_absolute_system_path_is_other(self) -> None:
        evidence = ProcessEvidenceProjector().project(
            _start(tool_name="read_file", args={"file_path": "/etc/passwd"}),
            sequence=1,
        )
        assert evidence is not None
        assert evidence.target_scope is TargetScope.OTHER

    def test_no_path_is_other(self) -> None:
        evidence = ProcessEvidenceProjector().project(
            _start(args={"command": "git status"}), sequence=1
        )
        assert evidence is not None
        assert evidence.target_scope is TargetScope.OTHER

    def test_custom_rules_override(self) -> None:
        projector = ProcessEvidenceProjector(
            path_scope_rules=PathScopeRules(test_prefixes=("specs/",))
        )
        evidence = projector.project(
            _start(tool_name="write_file", args={"file_path": "specs/x_test.py"}),
            sequence=1,
        )
        assert evidence is not None
        assert evidence.target_scope is TargetScope.TEST

    def test_path_never_persisted(self) -> None:
        recorder = TraceRecorder()
        recorder.record(
            _start(tool_name="edit_file", args={"file_path": "tests/test_secret.py"})
        )
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "trace.json"
            recorder.write_json(path)
            text = path.read_text(encoding="utf-8")
            assert "tests/test_secret.py" not in text
            assert "test_secret" not in text


class TestValidationCommand:
    def test_pytest_matches_short_form(self) -> None:
        projector = ProcessEvidenceProjector(
            validation_commands=("python -m pytest -q",)
        )
        evidence = projector.project(
            _start(args={"command": "pytest -q tests/test_a.py"}), sequence=1
        )
        assert evidence is not None
        assert evidence.validation_command is True
        assert evidence.validation_command_id == "validation-0"
        assert evidence.command_digest is not None

    def test_exact_command_matches(self) -> None:
        projector = ProcessEvidenceProjector(
            validation_commands=("python -m pytest -q",)
        )
        evidence = projector.project(
            _start(args={"command": "python -m pytest -q"}), sequence=1
        )
        assert evidence is not None
        assert evidence.validation_command is True

    def test_unrelated_command_does_not_match(self) -> None:
        projector = ProcessEvidenceProjector(
            validation_commands=("python -m pytest -q",)
        )
        evidence = projector.project(
            _start(args={"command": "git status"}), sequence=1
        )
        assert evidence is not None
        assert evidence.validation_command is False
        assert evidence.validation_command_id is None

    def test_second_declared_command_gets_own_id(self) -> None:
        projector = ProcessEvidenceProjector(
            validation_commands=("python -m pytest -q", "npm test")
        )
        evidence = projector.project(
            _start(args={"command": "npm test -- --run"}), sequence=1
        )
        assert evidence is not None
        assert evidence.validation_command_id == "validation-1"

    def test_no_commands_skips_match(self) -> None:
        evidence = ProcessEvidenceProjector().project(_start(), sequence=1)
        assert evidence is not None
        assert evidence.validation_command is False

    def test_command_never_persisted(self) -> None:
        recorder = TraceRecorder(
            projector=ProcessEvidenceProjector(
                validation_commands=("python -m pytest -q",)
            )
        )
        recorder.record(_start(args={"command": "pytest -q --secret-flag"}))
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "trace.json"
            recorder.write_json(path)
            text = path.read_text(encoding="utf-8")
            assert "secret-flag" not in text
            assert "pytest -q" not in text


class TestCompactionAndTermination:
    def test_compaction_started(self) -> None:
        evidence = ProcessEvidenceProjector().project(
            CompactionStartedEvent(), sequence=7
        )
        assert evidence is not None
        assert evidence.compaction is CompactionState.STARTED

    def test_compaction_completed(self) -> None:
        evidence = ProcessEvidenceProjector().project(
            CompactionCompletedEvent(), sequence=8
        )
        assert evidence is not None
        assert evidence.compaction is CompactionState.COMPLETED

    def test_turn_failed(self) -> None:
        evidence = ProcessEvidenceProjector().project(
            TurnFailedEvent(message=UserMessage(content="x")), sequence=9
        )
        assert evidence is not None
        assert evidence.termination is TerminationKind.TURN_FAILED

    def test_cancelled(self) -> None:
        evidence = ProcessEvidenceProjector().project(
            CancelledEvent(), sequence=10
        )
        assert evidence is not None
        assert evidence.termination is TerminationKind.CANCELLED


class TestUnknownAndRecorder:
    def test_unknown_event_returns_none_without_error(self) -> None:
        assert ProcessEvidenceProjector().project({"type": "mystery"}, sequence=1) is None

    def test_recorder_produces_evidence_alongside_events(self) -> None:
        recorder = TraceRecorder()
        recorder.record(_start())
        recorder.record(_end(is_error=True))
        assert len(recorder.events) == 2
        assert len(recorder.evidence) == 2
        assert [e.sequence for e in recorder.evidence] == [1, 2]
        assert [e.tool_phase for e in recorder.evidence] == [
            ToolPhase.START,
            ToolPhase.END,
        ]

    def test_record_tool_call_produces_synthetic_evidence(self) -> None:
        recorder = TraceRecorder()
        recorder.record_tool_call(
            tool_name="bash",
            arguments={"command": "pytest -q"},
        )
        assert len(recorder.evidence) == 1
        assert recorder.evidence[0].tool_phase is ToolPhase.END
        assert recorder.evidence[0].tool_name == "bash"

    def test_write_json_contains_evidence_array(self, tmp_path: Path) -> None:
        recorder = TraceRecorder()
        recorder.record(_start())
        path = tmp_path / "trace.json"
        recorder.write_json(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert "evidence" in payload
        assert len(payload["evidence"]) == 1

    def test_evidence_json_round_trip(self) -> None:
        evidence = ProcessEvidence(
            sequence=1,
            tool_call_id="call-1",
            tool_phase=ToolPhase.END,
            tool_name="run_shell",
            is_error=True,
            target_scope=TargetScope.SOURCE,
            validation_command=True,
            validation_command_id="validation-0",
        )
        restored = ProcessEvidence.from_json(evidence.canonical_json())
        assert restored == evidence

    def test_deterministic_projection(self) -> None:
        projector = ProcessEvidenceProjector(
            validation_commands=("python -m pytest -q",)
        )
        assert projector.project(_start(), sequence=1) == projector.project(
            _start(), sequence=1
        )