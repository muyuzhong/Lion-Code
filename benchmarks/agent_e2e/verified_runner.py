"""Harbor routine trial 与官方 Harness 的最小串联入口。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifact import (
    ARTIFACT_BUILDER_VERSION,
    ArtifactBuildError,
    CommitArtifact,
    CommitArtifactBuilder,
)
from .harbor_runner import (
    HARBOR_VERSION,
    HarborExecutionOutput,
    HarborExecutionRequest,
    HarborSingleTaskRunner,
)
from .harness import harness_result_to_task_result
from .harness_runner import (
    SWEBENCH_VERSION,
    HarnessExecutionRequest,
    OfficialSWEbenchHarnessRunner,
)
from .models import (
    AdapterStatus,
    ExperimentManifest,
    FailureSource,
    HarnessRecheckResult,
    ReportStatus,
    ResultValidity,
    TaskResult,
    TaskSpec,
    TaskVerdict,
    TrialExecution,
    TrialExecutionStatus,
    VerifiedEvaluationReport,
    WorkerResult,
)
from .report import render_chinese_markdown
from .trace import redact_text


@dataclass(frozen=True, slots=True)
class VerifiedExecutionRequest:
    """一个 commit、一个公开任务和一个 output root 的执行请求。"""

    repository_root: Path
    commit_sha: str
    manifest: ExperimentManifest
    task: TaskSpec
    output_dir: Path
    python_executable: str | Path
    harness_python: str | Path
    harbor_executable: str = "harbor"


@dataclass(frozen=True, slots=True)
class VerifiedExecutionOutput:
    """可写入 JSON 的 Verified 报告及本次运行的内存产物引用。"""

    report: VerifiedEvaluationReport
    artifact: CommitArtifact | None = None
    harbor: HarborExecutionOutput | None = None
    harness: HarnessRecheckResult | None = None


def run_verified_evaluation(
    request: VerifiedExecutionRequest,
) -> VerifiedExecutionOutput:
    """按固定顺序执行 artifact → Harbor → 官方 Harness。"""

    _validate_request(request)
    output_dir = request.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        request.manifest.profile.require_online_budget()
    except ValueError as error:
        return _blocked_output(request, str(error))

    artifact: CommitArtifact | None = None
    try:
        artifact = CommitArtifactBuilder(
            request.repository_root,
            python_executable=request.python_executable,
            staging_root=output_dir / ".staging",
        ).build(request.commit_sha, output_dir / "artifacts")
    except (ArtifactBuildError, OSError, RuntimeError) as error:
        reason, _ = redact_text(
            str(error) or "Commit artifact build failed", max_length=320
        )
        return _blocked_output(request, reason)
    if not artifact.commit_sha.startswith(request.manifest.agent_code_sha.lower()):
        return _invalid_output(
            request, "Commit does not match manifest agent_code_sha", artifact
        )

    harbor_output = HarborSingleTaskRunner().run(
        HarborExecutionRequest(
            repository_root=request.repository_root,
            artifact=artifact,
            manifest=request.manifest,
            task=request.task,
            output_dir=output_dir,
            harbor_executable=request.harbor_executable,
        )
    )
    harness_result: HarnessRecheckResult | None = None
    worker = harbor_output.worker_result
    task_result: TaskResult
    if harbor_output.patch_path is None or harbor_output.result.patch_sha256 is None:
        task_result = _nonofficial_task_result(
            request,
            status=harbor_output.result.status,
            reason=(
                harbor_output.result.reason
                or "Harbor did not export a patch for official recheck"
            ),
            worker=worker,
            patch_sha256=harbor_output.result.patch_sha256,
        )
    else:
        harness_output = OfficialSWEbenchHarnessRunner().run(
            HarnessExecutionRequest(
                instance_id=_swebench_instance_id(request.task),
                patch_path=harbor_output.patch_path,
                patch_sha256=harbor_output.result.patch_sha256,
                model_name=request.manifest.profile.model,
                run_id=request.manifest.run_id,
                output_dir=output_dir,
                timeout_seconds=request.manifest.timeout_seconds,
                image_digest=request.manifest.verifier_image_digest,
                python_executable=request.harness_python,
            )
        )
        harness_result = harness_output.result
        task_result = harness_result_to_task_result(
            harness_result,
            manifest=request.manifest,
            attempt=1,
            supports_official_scores=True,
            agent_run=worker.agent_run if worker is not None else None,
        )
        if worker is not None and task_result.trace_summary is None:
            task_result = task_result.model_copy(
                update={"trace_summary": worker.trace_summary}
            )

    report_status = (
        ReportStatus.OFFICIAL
        if task_result.official
        else ReportStatus.BLOCKED
        if task_result.verdict is TaskVerdict.BLOCKED
        else ReportStatus.OFFLINE
    )
    report = VerifiedEvaluationReport(
        manifest=request.manifest,
        task_result=task_result,
        status=report_status,
        provenance=artifact.to_provenance(
            harbor_version=HARBOR_VERSION,
            swebench_version=SWEBENCH_VERSION,
            image_digest=request.manifest.verifier_image_digest,
            dependency_fingerprint=_dependency_fingerprint(),
        ),
        trial=_trial_from_harbor(request, harbor_output),
        harbor=harbor_output.result,
        harness=harness_result,
    )
    return VerifiedExecutionOutput(
        report=report,
        artifact=artifact,
        harbor=harbor_output,
        harness=harness_result,
    )


def write_verified_report(
    report: VerifiedEvaluationReport,
    output_dir: str | Path,
) -> tuple[Path, Path]:
    """写入 Verified JSON 与中文摘要，不暴露原始外部输出。"""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "verified-report.json"
    markdown_path = destination / "verified-report.md"
    json_path.write_text(report.canonical_json() + "\n", encoding="utf-8")
    markdown_path.write_text(
        render_chinese_markdown(_as_evaluation_report(report)),
        encoding="utf-8",
    )
    return json_path, markdown_path


def _validate_request(request: VerifiedExecutionRequest) -> None:
    if request.task.task_id not in request.manifest.task_ids:
        raise ValueError("Verified task is not selected by manifest")
    if request.commit_sha != request.commit_sha.strip():
        raise ValueError("commit_sha must not contain surrounding whitespace")
    if request.manifest.repeats != 1:
        raise ValueError("Verified single-task runner requires repeats=1")


def _blocked_output(
    request: VerifiedExecutionRequest,
    reason: str,
) -> VerifiedExecutionOutput:
    return _make_nonofficial_output(
        request,
        _blocked_task_result(request, reason=reason, worker=None, patch_sha256=None),
    )


def _invalid_output(
    request: VerifiedExecutionRequest,
    reason: str,
    artifact: CommitArtifact,
) -> VerifiedExecutionOutput:
    result = TaskResult(
        task_id=request.task.task_id,
        attempt=1,
        verdict=TaskVerdict.INVALID,
        validity=ResultValidity.INVALID,
        invalid_reason=reason,
    )
    report = VerifiedEvaluationReport(
        manifest=request.manifest,
        task_result=result,
        status=ReportStatus.OFFLINE,
        provenance=artifact.to_provenance(
            harbor_version=HARBOR_VERSION,
            swebench_version=SWEBENCH_VERSION,
            dependency_fingerprint=_dependency_fingerprint(),
        ),
    )
    return VerifiedExecutionOutput(report=report, artifact=artifact)


def _make_nonofficial_output(
    request: VerifiedExecutionRequest,
    result: TaskResult,
) -> VerifiedExecutionOutput:
    report = VerifiedEvaluationReport(
        manifest=request.manifest,
        task_result=result,
        status=(
            ReportStatus.BLOCKED
            if result.verdict is TaskVerdict.BLOCKED
            else ReportStatus.OFFLINE
        ),
    )
    return VerifiedExecutionOutput(report=report)


def _blocked_task_result(
    request: VerifiedExecutionRequest,
    *,
    reason: str,
    worker: WorkerResult | None,
    patch_sha256: str | None,
) -> TaskResult:
    return TaskResult(
        task_id=request.task.task_id,
        attempt=1,
        verdict=TaskVerdict.BLOCKED,
        validity=ResultValidity.BLOCKED,
        official=False,
        patch_sha256=patch_sha256,
        patch_applied=patch_sha256 is not None,
        agent_run=worker.agent_run if worker is not None else None,
        trace_summary=worker.trace_summary if worker is not None else None,
        invalid_reason=reason[:320],
    )


def _nonofficial_task_result(
    request: VerifiedExecutionRequest,
    *,
    status: AdapterStatus,
    reason: str,
    worker: WorkerResult | None,
    patch_sha256: str | None,
) -> TaskResult:
    if status in {
        AdapterStatus.UNAVAILABLE,
        AdapterStatus.BLOCKED,
        AdapterStatus.TIMEOUT,
    }:
        return _blocked_task_result(
            request,
            reason=reason,
            worker=worker,
            patch_sha256=patch_sha256,
        )
    return TaskResult(
        task_id=request.task.task_id,
        attempt=1,
        verdict=TaskVerdict.INVALID,
        validity=ResultValidity.INVALID,
        official=False,
        patch_sha256=patch_sha256,
        patch_applied=patch_sha256 is not None,
        agent_run=worker.agent_run if worker is not None else None,
        trace_summary=worker.trace_summary if worker is not None else None,
        invalid_reason=reason[:320],
    )


def _trial_from_harbor(
    request: VerifiedExecutionRequest,
    output: HarborExecutionOutput,
) -> TrialExecution:
    routine = output.result
    status = routine.execution_status
    if status is TrialExecutionStatus.COMPLETED:
        failure_source = None
        reason = None
    else:
        failure_source = routine.failure_source or FailureSource.HARBOR
        reason = routine.reason or "Harbor trial did not complete"
    return TrialExecution(
        run_id=request.manifest.run_id,
        task_id=request.task.task_id,
        attempt=1,
        status=status,
        failure_source=failure_source,
        reason=reason,
        wall_time_seconds=routine.wall_time_seconds or 0,
        patch_sha256=routine.patch_sha256,
        trace_digest=(
            output.worker_result.trace_summary.trace_digest
            if output.worker_result is not None
            and output.worker_result.trace_summary is not None
            else None
        ),
    )


def _swebench_instance_id(task: TaskSpec) -> str:
    value = task.extensions.get("swebench_instance_id", task.task_id)
    if not isinstance(value, str) or not value.strip() or "/" in value or "\\" in value:
        raise ValueError("SWE-bench instance_id is invalid")
    return value


def _dependency_fingerprint() -> str:
    return hashlib.sha256(
        f"harbor=={HARBOR_VERSION};swebench=={SWEBENCH_VERSION};"
        f"artifact-builder=={ARTIFACT_BUILDER_VERSION}".encode()
    ).hexdigest()


def _as_evaluation_report(report: VerifiedEvaluationReport) -> Any:
    from .models import EvaluationReport

    return EvaluationReport(
        manifest=report.manifest,
        results=(report.task_result,),
        status=report.status,
    )


__all__ = [
    "VerifiedExecutionOutput",
    "VerifiedExecutionRequest",
    "run_verified_evaluation",
    "write_verified_report",
]
