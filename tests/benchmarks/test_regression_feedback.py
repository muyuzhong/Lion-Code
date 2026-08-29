"""回归门禁、失败归因和反馈样本防泄漏边界。"""

from __future__ import annotations

import pytest

from tests.benchmarks.fixtures.verified_task_1 import (
    AGENT_CODE_SHA,
    EVALUATOR_CODE_SHA,
    make_task as make_verified_task,
)
from benchmarks.agent_e2e.catalog import freeze_catalog
from benchmarks.agent_e2e.external_anchor import (
    CalibrationPoint,
    CalibrationProfileKind,
    CalibrationReport,
    ExternalAnchorEnvironment,
    ExternalImage,
)
from benchmarks.agent_e2e.models import (
    AgentRunSummary,
    Catalog,
    EvaluationReport,
    ExperimentManifest,
    ExperimentProfile,
    ResultValidity,
    TaskResult,
    TaskSpec,
    TaskSplit,
    TaskVerdict,
    VerifierOutcome,
    VerifierResult,
)
from benchmarks.agent_e2e.regression import (
    ChangeKind,
    FailureFeedbackError,
    FailureResponsibility,
    FailureTriage,
    GeneralizationStatus,
    RegressionGateLedger,
    ReproductionStatus,
    admit_failure_to_regression,
    classify_failure,
    deduplicate_failure_records,
    evaluate_regression_gate,
    load_gate_ledger,
    write_gate_ledger,
)
from benchmarks.agent_e2e.report import build_report
from benchmarks.agent_e2e.trace import TraceEvent


def _task(task_id: str, *, split: TaskSplit = TaskSplit.REGRESSION) -> TaskSpec:
    return make_verified_task(
        task_id=task_id,
        split=split,
        verifier_identity="hidden-v1",
        difficulty=1,
        public_setup=("python -m pip install -e .",),
        public_validation_commands=("python -m pytest -q",),
        involved_files=("lion_code/meta_agent.py",),
    )


def _report(
    run_id: str,
    outcomes: tuple[bool, ...],
    *,
    prompt_version: str,
    model: str = "fake-model",
) -> EvaluationReport:
    tasks = tuple(_task(f"task-{index}") for index in range(1, len(outcomes) + 1))
    catalog = Catalog(catalog_id="gate-fixture", catalog_version="v1", tasks=tasks)
    profile = ExperimentProfile(
        profile_id=f"profile-{prompt_version}",
        model=model,
        provider="fake",
        prompt_version=prompt_version,
        compression_version="compression-v1",
        tool_policy_version="tools-v1",
        seed=7,
        repeats=1,
        timeout_seconds=30,
        budget_usd=1,
        agent_code_sha=AGENT_CODE_SHA,
        credential_env_vars=("EVAL_API_KEY",),
    )
    manifest = ExperimentManifest(
        run_id=run_id,
        agent_code_sha=profile.agent_code_sha,
        evaluator_code_sha=EVALUATOR_CODE_SHA,
        catalog=freeze_catalog(catalog),
        profile=profile,
        profile_fingerprint=profile.fingerprint(),
        task_ids=tuple(task.task_id for task in tasks),
        seed=profile.seed,
        repeats=profile.repeats,
        timeout_seconds=profile.timeout_seconds,
        budget_usd=profile.budget_usd,
        platform="linux-amd64",
        agent_image_digest="sha256:agent",
        verifier_image_digest="sha256:verifier",
    )
    return build_report(
        manifest=manifest,
        results=tuple(
            _failed_or_passed_result(task.task_id, passed=passed)
            for task, passed in zip(tasks, outcomes, strict=True)
        ),
    )


def _failed_or_passed_result(
    task_id: str,
    *,
    passed: bool,
    stop_reason: str = "completed",
) -> TaskResult:
    outcome = VerifierOutcome.PASSED if passed else VerifierOutcome.FAILED
    verdict = TaskVerdict.PASSED if passed else TaskVerdict.FAILED
    return TaskResult(
        task_id=task_id,
        attempt=1,
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
) -> TraceEvent:
    return TraceEvent(
        sequence=sequence,
        event_type=event_type,
        summary="受控事件",
        payload_digest="e" * 64,
        tool_name=tool_name,
        argument_digest=argument_digest,
        workspace_fingerprint=workspace_fingerprint,
    )


def _classify(task_result: TaskResult, events: tuple[TraceEvent, ...]):
    return classify_failure(
        task_result,
        events,
        allowed_tool_names={"read_file"},
        reproduction_command="python -m pytest -q tests/benchmarks",
        triage_owner="eval-owner",
    )


def _accepted_calibration(
    baseline: EvaluationReport,
    candidate: EvaluationReport,
) -> CalibrationReport:
    environment = ExternalAnchorEnvironment(
        manifest_fingerprint="f" * 64,
        dataset_revision="a" * 40,
        dataset_file_sha256="b" * 64,
        evaluator_revision="c" * 40,
        platform="linux",
        images=(
            ExternalImage(
                instance_id="anchor-task",
                image_reference="fixture:latest",
                image_digest="sha256:fixture",
            ),
        ),
    )
    fingerprints = (
        baseline.manifest.profile_fingerprint,
        candidate.manifest.profile_fingerprint,
        "1" * 64,
        "2" * 64,
        "3" * 64,
    )
    kinds = (
        CalibrationProfileKind.BASELINE,
        CalibrationProfileKind.CANDIDATE,
        CalibrationProfileKind.CANDIDATE,
        CalibrationProfileKind.CANDIDATE,
        CalibrationProfileKind.DEGRADED,
    )
    points = tuple(
        CalibrationPoint(
            profile_id=f"calibration-{index}",
            profile_fingerprint=fingerprint,
            profile_kind=kind,
            self_holdout_passed=10 - index,
            self_holdout_denominator=10,
            external_report_fingerprint=f"{index}" * 64,
            external_passed=20 - index * 2,
            external_denominator=20,
            external_success_rate=(20 - index * 2) / 20,
            environment=environment,
        )
        for index, (fingerprint, kind) in enumerate(zip(fingerprints, kinds, strict=True))
    )
    return CalibrationReport(
        points=points,
        spearman_rho=0.9,
        direction_pairs=10,
        direction_agreement=0.9,
        accepted=True,
    )


def test_gate_statuses_and_rejected_candidate_ledger(tmp_path) -> None:
    baseline = _report("baseline", (True, True, True), prompt_version="prompt-v1")
    candidate = _report("candidate", (True, True, True), prompt_version="prompt-v2")

    passed = evaluate_regression_gate(
        baseline,
        candidate,
        declared_changes=(ChangeKind.PROMPT,),
    )

    assert passed.gate.status.value == "pass"
    assert passed.generalization_status is GeneralizationStatus.SELF_ONLY

    calibrated = evaluate_regression_gate(
        baseline,
        candidate,
        declared_changes=(ChangeKind.PROMPT,),
        calibration=_accepted_calibration(baseline, candidate),
    )
    assert calibrated.generalization_status is GeneralizationStatus.EXTERNAL_CALIBRATED

    degraded = _report("degraded", (False, False, False), prompt_version="prompt-v2")
    rejected = evaluate_regression_gate(
        baseline,
        degraded,
        declared_changes=(ChangeKind.PROMPT,),
    )
    assert rejected.gate.status.value == "reject"
    assert "Catastrophic" in rejected.gate.reason

    ledger = RegressionGateLedger().record(rejected)
    ledger = ledger.record(rejected, merged=True, merge_reference="intentional-test")
    assert ledger.intercepted_count == 1
    path = write_gate_ledger(ledger, output_path=tmp_path / "gate-ledger.json")
    assert load_gate_ledger(path) == ledger

    waived = evaluate_regression_gate(
        baseline,
        _report("waived", (False, False, False), prompt_version="prompt-v2"),
        declared_changes=(ChangeKind.PROMPT,),
        waiver_reason="由人工批准的临时实验。",
    )
    assert waived.gate.status.value == "waived"

    invalid = evaluate_regression_gate(
        baseline,
        _report(
            "incomparable",
            (True, True, True),
            prompt_version="prompt-v2",
            model="other-model",
        ),
        declared_changes=(ChangeKind.PROMPT,),
    )
    assert invalid.gate.status.value == "invalid"
    assert invalid.baseline_score is None

    undeclared = evaluate_regression_gate(
        baseline,
        candidate,
        declared_changes=(),
    )
    assert undeclared.gate.status.value == "invalid"
    assert undeclared.declared_changes == ()


def test_failure_rules_cover_all_modes_and_infrastructure_priority() -> None:
    failed = _failed_or_passed_result("failure-task", passed=False)
    loop_events = tuple(
        _event(
            sequence,
            "ToolCall",
            tool_name="read_file",
            argument_digest="f" * 64,
            workspace_fingerprint="a" * 64,
        )
        for sequence in range(1, 4)
    )
    loop = _classify(failed, loop_events)
    assert loop.primary_mode.value == "loop"
    assert loop.evidence_offsets == (1, 2, 3)

    context = _classify(
        failed,
        (_event(1, "ContextCompacted"),),
    )
    assert context.primary_mode.value == "context_decay"
    assert context.evidence_offsets == (1,)

    tool_misuse = _classify(
        failed,
        (
            _event(
                1,
                "ToolCall",
                tool_name="shell",
                argument_digest="f" * 64,
                workspace_fingerprint="a" * 64,
            ),
        ),
    )
    assert tool_misuse.primary_mode.value == "tool_misuse"
    assert tool_misuse.evidence_offsets == (1,)

    premature = _classify(
        _failed_or_passed_result(
            "premature-task",
            passed=False,
            stop_reason="max_turns",
        ),
        (),
    )
    assert premature.primary_mode.value == "premature_termination"
    assert premature.evidence_offsets == ()

    blocked = TaskResult(
        task_id="blocked-task",
        attempt=1,
        verdict=TaskVerdict.BLOCKED,
        validity=ResultValidity.BLOCKED,
        official=False,
    )
    infrastructure = _classify(blocked, loop_events)
    assert infrastructure.primary_mode.value == "infrastructure"
    assert infrastructure.evidence_offsets == ()


def test_deduplication_and_holdout_feedback_retirement() -> None:
    loop_events = tuple(
        _event(
            sequence,
            "ToolCall",
            tool_name="read_file",
            argument_digest="f" * 64,
            workspace_fingerprint="a" * 64,
        )
        for sequence in range(1, 4)
    )
    source_result = _failed_or_passed_result("holdout-source", passed=False)
    first = _classify(source_result, loop_events)
    second = _classify(
        _failed_or_passed_result("same-failure-new-task", passed=False),
        loop_events,
    )
    deduplicated = deduplicate_failure_records((first, second))
    assert not deduplicated[0].deduplicated
    assert deduplicated[1].deduplicated

    source_task = _task("holdout-source", split=TaskSplit.HOLDOUT)
    feedback_task = _task("feedback-loop-v2", split=TaskSplit.REGRESSION)
    triage = FailureTriage(
        failure=deduplicated[0],
        reproduction_status=ReproductionStatus.REPRODUCED,
        responsibility=FailureResponsibility.AGENT,
        review_reason="冻结输入可稳定复现，责任归属为 Agent。",
        reviewer="eval-owner",
    )
    with pytest.raises(FailureFeedbackError, match="retired"):
        admit_failure_to_regression(
            triage,
            source_task=source_task,
            feedback_task=feedback_task,
            active_holdout_task_ids=("holdout-source", "remaining-holdout"),
            retired_holdout_task_ids=(),
        )

    admission = admit_failure_to_regression(
        triage,
        source_task=source_task,
        feedback_task=feedback_task,
        active_holdout_task_ids=("holdout-source", "remaining-holdout"),
        retired_holdout_task_ids=("holdout-source",),
    )
    assert admission.failure.feedback_split is TaskSplit.REGRESSION
    assert admission.source_task_id not in admission.active_holdout_task_ids_after_feedback
    assert admission.failure.holdout_exclusion_reason is not None
