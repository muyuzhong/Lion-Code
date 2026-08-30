"""Regression Probe 单元测试:probe_holds + 失败片段最小化(验收 1/2)。"""

from __future__ import annotations

import pytest

from benchmarks.agent_e2e.evidence import (
    CompactionState,
    ProcessEvidence,
    TargetScope,
    ToolPhase,
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
    ProcessViolationType,
)
from benchmarks.agent_e2e.regression_probe import (
    minimize_failure_evidence,
    probe_holds,
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


class TestProbeHolds:
    def test_empty_evidence_is_false(self) -> None:
        # 空切片降级为 EVIDENCE_UNAVAILABLE,不是任何 violation。
        assert (
            probe_holds(
                ProcessViolationType.TOOL_ERROR_NOT_RECOVERED,
                (),
                _task(),
                _result(passed=False),
            )
            is False
        )

    def test_unrecovered_error_requires_repeats(self) -> None:
        task = _task()
        result = _result(passed=False)
        insufficient = (
            _start(1, "c1", "edit_file", _fp(9)),
            _end(2, "c1", "edit_file", error=True),
            _start(3, "c2", "edit_file", _fp(9)),
            _end(4, "c2", "edit_file", error=True),
        )
        assert (
            probe_holds(
                ProcessViolationType.TOOL_ERROR_NOT_RECOVERED,
                insufficient,
                task,
                result,
            )
            is False
        )
        sufficient = (
            *insufficient,
            _start(5, "c3", "edit_file", _fp(9)),
            _end(6, "c3", "edit_file", error=True),
        )
        assert (
            probe_holds(
                ProcessViolationType.TOOL_ERROR_NOT_RECOVERED,
                sufficient,
                task,
                result,
            )
            is True
        )

    def test_test_tampering_requires_protected_scope(self) -> None:
        task = _task()
        result = _result(passed=False)
        safe = (_start(1, "c1", "edit_file", _fp(9), target_scope=TargetScope.SOURCE),)
        assert (
            probe_holds(ProcessViolationType.TEST_TAMPERING, safe, task, result)
            is False
        )
        tampered = (
            _start(1, "c1", "edit_file", _fp(9), target_scope=TargetScope.TEST),
        )
        assert (
            probe_holds(ProcessViolationType.TEST_TAMPERING, tampered, task, result)
            is True
        )


class TestMinimizeUnrecoveredError:
    """验收 1:长 unrecovered-error 轨迹能裁成更短片段,仍触发同一 violation。"""

    def test_long_trace_trims_to_shorter_fragment(self) -> None:
        task = _task()
        result = _result(passed=False)
        # 长轨迹:两段 read + 三次同指纹 edit 失败 + 尾部无关 read。
        evidence = (
            _start(1, "c0", "read_file", _fp(1)),
            _end(2, "c0", "read_file"),
            _start(3, "c1", "read_file", _fp(2)),
            _end(4, "c1", "read_file"),
            _start(5, "c3", "edit_file", _fp(9)),
            _end(6, "c3", "edit_file", error=True),
            _start(7, "c4", "edit_file", _fp(9)),
            _end(8, "c4", "edit_file", error=True),
            _start(9, "c5", "edit_file", _fp(9)),
            _end(10, "c5", "edit_file", error=True),
            _start(11, "c6", "read_file", _fp(3)),
            _end(12, "c6", "read_file"),
        )
        minimized = minimize_failure_evidence(
            violation_type=ProcessViolationType.TOOL_ERROR_NOT_RECOVERED,
            task=task,
            task_result=result,
            evidence=evidence,
        )
        assert len(minimized) < len(evidence)
        assert (
            probe_holds(
                ProcessViolationType.TOOL_ERROR_NOT_RECOVERED,
                minimized,
                task,
                result,
            )
            is True
        )
        # 必要事件仍在:失败 end + 至少两次同指纹后续调用。
        assert any(
            item.tool_phase is ToolPhase.END and item.is_error for item in minimized
        )
        assert (
            sum(
                item.tool_fingerprint == _fp(9) and item.tool_phase is ToolPhase.START
                for item in minimized
            )
            >= 3
        )

    def test_fragment_is_minimal_single_event_removal_breaks(self) -> None:
        """验收 2:删除任意一个必要事件后 violation 不再成立。"""
        task = _task()
        result = _result(passed=False)
        evidence = (
            _start(1, "c0", "read_file", _fp(1)),
            _end(2, "c0", "read_file"),
            _start(3, "c1", "read_file", _fp(2)),
            _end(4, "c1", "read_file"),
            _start(5, "c3", "edit_file", _fp(9)),
            _end(6, "c3", "edit_file", error=True),
            _start(7, "c4", "edit_file", _fp(9)),
            _end(8, "c4", "edit_file", error=True),
            _start(9, "c5", "edit_file", _fp(9)),
            _end(10, "c5", "edit_file", error=True),
            _start(11, "c6", "read_file", _fp(3)),
            _end(12, "c6", "read_file"),
        )
        minimized = minimize_failure_evidence(
            violation_type=ProcessViolationType.TOOL_ERROR_NOT_RECOVERED,
            task=task,
            task_result=result,
            evidence=evidence,
        )
        assert len(minimized) >= 4
        for index in range(len(minimized)):
            candidate = minimized[:index] + minimized[index + 1 :]
            assert (
                probe_holds(
                    ProcessViolationType.TOOL_ERROR_NOT_RECOVERED,
                    candidate,
                    task,
                    result,
                )
                is False
            ), f"删除第 {index} 个事件后 violation 仍成立,片段未达最小"

    def test_raises_when_initial_slice_does_not_hold(self) -> None:
        task = _task()
        result = _result(passed=False)
        clean = (
            _start(1, "c1", "read_file", _fp(1)),
            _end(2, "c1", "read_file"),
        )
        with pytest.raises(ValueError):
            minimize_failure_evidence(
                violation_type=ProcessViolationType.TOOL_ERROR_NOT_RECOVERED,
                task=task,
                task_result=result,
                evidence=clean,
            )


class TestMinimizeContextRegression:
    def test_context_regression_keeps_boundary_events(self) -> None:
        task = _task()
        result = _result(passed=False)
        # failed call + compaction + compaction 后同指纹 call + 无关 read。
        evidence = (
            _start(1, "c1", "edit_file", _fp(9)),
            _end(2, "c1", "edit_file", error=True),
            ProcessEvidence(sequence=3, compaction=CompactionState.STARTED),
            ProcessEvidence(sequence=4, compaction=CompactionState.COMPLETED),
            _start(5, "c2", "edit_file", _fp(9)),
            _end(6, "c2", "edit_file"),
            _start(7, "c3", "read_file", _fp(1)),
            _end(8, "c3", "read_file"),
        )
        minimized = minimize_failure_evidence(
            violation_type=ProcessViolationType.CONTEXT_REGRESSION,
            task=task,
            task_result=result,
            evidence=evidence,
        )
        assert len(minimized) < len(evidence)
        assert (
            probe_holds(
                ProcessViolationType.CONTEXT_REGRESSION, minimized, task, result
            )
            is True
        )
        # 三个边界条件都必须保留:失败 end、compaction、compaction 后同指纹 call。
        assert any(
            item.tool_phase is ToolPhase.END and item.is_error for item in minimized
        )
        assert any(item.compaction is not None for item in minimized)
        assert any(
            item.tool_name == "edit_file" and not item.is_error for item in minimized
        )


class TestMinimizeTestTampering:
    def test_tampering_reduces_to_single_event(self) -> None:
        task = _task()
        result = _result(passed=False)
        evidence = (
            _start(1, "c1", "read_file", _fp(1)),
            _end(2, "c1", "read_file"),
            _start(3, "c2", "edit_file", _fp(9), target_scope=TargetScope.TEST),
            _end(4, "c2", "edit_file"),
            _start(5, "c3", "read_file", _fp(2)),
            _end(6, "c3", "read_file"),
        )
        minimized = minimize_failure_evidence(
            violation_type=ProcessViolationType.TEST_TAMPERING,
            task=task,
            task_result=result,
            evidence=evidence,
        )
        assert len(minimized) == 1
        assert minimized[0].target_scope is TargetScope.TEST


class TestMinimizeWithCustomProbe:
    def test_minimize_uses_injected_probe(self) -> None:
        task = _task()
        result = _result(passed=False)
        evidence = tuple(
            _start(index, f"c{index}", "read_file", _fp(index)) for index in range(1, 6)
        )

        def at_least_two(_vt, slice_, _tk, _tr) -> bool:
            return len(slice_) >= 2

        minimized = minimize_failure_evidence(
            violation_type=ProcessViolationType.TEST_TAMPERING,
            task=task,
            task_result=result,
            evidence=evidence,
            probe=at_least_two,
        )
        assert len(minimized) == 2
        assert at_least_two(
            ProcessViolationType.TEST_TAMPERING, minimized, task, result
        )
