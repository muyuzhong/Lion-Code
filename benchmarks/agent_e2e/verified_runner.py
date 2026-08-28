"""Verified 单题执行与后置分析/观测的最小串联入口。"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .artifact import (
    ARTIFACT_BUILDER_VERSION,
    ArtifactBuildError,
    CommitArtifact,
    CommitArtifactBuilder,
)
from .deepeval_analysis import (
    DeepEvalJudge,
    analyze_verified_report,
    build_deepeval_trajectory,
)
from .deepeval_metrics import DEEPEVAL_SDK_VERSION
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
    DeepEvalAnalysis,
    DeepEvalAnalysisStatus,
    DeepEvalTrajectory,
    ExperimentManifest,
    FailureSource,
    HarnessRecheckResult,
    OpikExportResult,
    OpikExportStatus,
    OpikTracePayload,
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
from .opik_export import (
    OPIK_SDK_VERSION,
    build_opik_trace_payload,
    publish_opik_trace,
)
from .report import render_verified_markdown
from .trace import TraceEvent, redact_text

VERIFIED_EXIT_COMPLETED = 0
VERIFIED_EXIT_SUBJECT_FAILED = 1
VERIFIED_EXIT_INFRA_FAILED = 2
VERIFIED_EXIT_INVALID = 3


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
    trajectory: DeepEvalTrajectory | None = None
    input_digest: str | None = None
    deepeval_judge_model: str | None = None
    deepeval_judge: DeepEvalJudge | None = None
    deepeval_timeout_seconds: float | None = 120.0
    opik_client: Any | None = None
    opik_environment: Mapping[str, str] | None = None
    opik_project_name: str | None = None
    opik_workspace: str | None = None
    opik_timeout_seconds: float = 30.0


@dataclass(frozen=True, slots=True)
class VerifiedExecutionOutput:
    """可写入 JSON 的 Verified 报告及本次运行的内存产物引用。"""

    report: VerifiedEvaluationReport
    artifact: CommitArtifact | None = None
    harbor: HarborExecutionOutput | None = None
    harness: HarnessRecheckResult | None = None
    trajectory: DeepEvalTrajectory | None = None
    opik_payload: OpikTracePayload | None = None


def run_verified_evaluation(
    request: VerifiedExecutionRequest,
    *,
    artifact_builder: Any | None = None,
    harbor_runner: Any | None = None,
    harness_runner: Any | None = None,
) -> VerifiedExecutionOutput:
    """按固定顺序执行 artifact → Harbor → Harness → DeepEval → Opik。

    三个前置执行器只作为窄的测试注入点；默认路径始终使用现有实现。后置
    分析和发布只消费 Harbor 已导出的受控轨迹，不会再次调用 Agent。
    """

    _validate_request(request)
    output_dir = request.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        request.manifest.profile.require_online_budget()
    except ValueError as error:
        return _blocked_output(request, str(error))

    artifact: CommitArtifact | None = None
    try:
        builder = (
            artifact_builder
            if artifact_builder is not None
            else CommitArtifactBuilder(
                request.repository_root,
                python_executable=request.python_executable,
                staging_root=output_dir / ".staging",
            )
        )
        artifact = builder.build(request.commit_sha, output_dir / "artifacts")
    except (ArtifactBuildError, OSError, RuntimeError) as error:
        reason, _ = redact_text(
            str(error) or "Commit artifact build failed", max_length=320
        )
        return _blocked_output(request, reason)
    if not artifact.commit_sha.startswith(request.manifest.agent_code_sha.lower()):
        return _invalid_output(
            request, "Commit does not match manifest agent_code_sha", artifact
        )

    harbor = harbor_runner if harbor_runner is not None else HarborSingleTaskRunner()
    harbor_output = harbor.run(
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
        harness = (
            harness_runner
            if harness_runner is not None
            else OfficialSWEbenchHarnessRunner()
        )
        harness_output = harness.run(
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
        harness_result = _normalize_harness_result(
            harness_output.result,
            task=request.task,
        )
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
        task_result = _merge_worker_result(task_result, worker)

    provenance = artifact.to_provenance(
        harbor_version=HARBOR_VERSION,
        swebench_version=SWEBENCH_VERSION,
        image_digest=request.manifest.verifier_image_digest,
        dependency_fingerprint=_dependency_fingerprint(),
    ).model_copy(
        update={
            "deepeval_version": DEEPEVAL_SDK_VERSION,
            "opik_version": OPIK_SDK_VERSION,
        }
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
        provenance=provenance,
        trial=_trial_from_harbor(request, harbor_output),
        harbor=harbor_output.result,
        harness=harness_result,
    )
    report, trajectory, opik_payload = _run_post_processing(
        report,
        request=request,
        output_dir=output_dir,
        harbor_output=harbor_output,
    )
    if trajectory is not None:
        _write_controlled_json(
            output_dir / "artifacts" / "deepeval-trajectory.json",
            trajectory,
        )
    if report.deepeval is not None:
        _write_controlled_json(
            output_dir / "artifacts" / "deepeval-analysis.json",
            report.deepeval,
        )
    if opik_payload is not None:
        _write_controlled_json(
            output_dir / "artifacts" / "opik-payload.json",
            opik_payload,
        )
    return VerifiedExecutionOutput(
        report=report,
        artifact=artifact,
        harbor=harbor_output,
        harness=harness_result,
        trajectory=trajectory,
        opik_payload=opik_payload,
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
        render_verified_markdown(report),
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
    if (
        request.trajectory is not None
        and request.trajectory.task_id != request.task.task_id
    ):
        raise ValueError("Verified trajectory task_id does not match the task")
    if request.input_digest is not None and not re.fullmatch(
        r"[0-9a-fA-F]{64}", request.input_digest
    ):
        raise ValueError("Verified input_digest must be a SHA-256 hex digest")
    if (
        request.deepeval_timeout_seconds is not None
        and request.deepeval_timeout_seconds <= 0
    ):
        raise ValueError("deepeval_timeout_seconds must be positive or None")
    if request.opik_timeout_seconds <= 0:
        raise ValueError("opik_timeout_seconds must be positive")


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
        cost_usd=(
            worker.agent_run.cost_usd
            if worker is not None and worker.agent_run is not None
            else 0
        ),
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
        cost_usd=(
            worker.agent_run.cost_usd
            if worker is not None and worker.agent_run is not None
            else 0
        ),
        invalid_reason=reason[:320],
    )


def _merge_worker_result(
    result: TaskResult,
    worker: WorkerResult | None,
) -> TaskResult:
    """把一次 Agent 的受控 usage/patch 摘要补回 Harness 结果。"""

    if worker is None:
        return result
    updates: dict[str, Any] = {}
    if worker.agent_run is not None:
        updates.update(
            {
                "agent_run": worker.agent_run,
                "cost_usd": worker.agent_run.cost_usd,
            }
        )
    if worker.patch_sha256 is not None and result.patch_sha256 is None:
        updates["patch_sha256"] = worker.patch_sha256
    if worker.patch_applied is not None:
        updates["patch_applied"] = worker.patch_applied
    if worker.trace_summary is not None:
        updates["trace_summary"] = worker.trace_summary
    return result.model_copy(update=updates) if updates else result


def _run_post_processing(
    report: VerifiedEvaluationReport,
    *,
    request: VerifiedExecutionRequest,
    output_dir: Path,
    harbor_output: HarborExecutionOutput,
) -> tuple[
    VerifiedEvaluationReport,
    DeepEvalTrajectory | None,
    OpikTracePayload | None,
]:
    """在确定性复核之后运行分析和发布；失败只落在各自字段。"""

    trajectory = _load_trajectory(
        request,
        output_dir=output_dir,
        harbor_output=harbor_output,
        task_result=report.task_result,
    )
    if trajectory is None:
        return report, None, None
    input_digest = request.input_digest or _verified_input_digest(request.task)
    judge_model = request.deepeval_judge_model or request.manifest.profile.model
    agent_model = request.manifest.profile.model
    judge_fingerprint = _judge_fingerprint(judge_model)
    try:
        analyzed = analyze_verified_report(
            report,
            input_digest=input_digest,
            trajectory=trajectory,
            judge_model=judge_model,
            judge=request.deepeval_judge,
            timeout_seconds=request.deepeval_timeout_seconds,
            agent_model=agent_model,
            judge_fingerprint=judge_fingerprint,
        )
        analysis = analyzed.deepeval
        if (
            analyzed.task_result != report.task_result
            or analysis is None
            or analysis.task_id != report.task_result.task_id
            or analysis.input_digest != input_digest
            or analysis.trajectory_digest != trajectory.trace_digest
        ):
            raise ValueError("DeepEval analysis changed or mismatched the report")
    except Exception as error:
        analysis = _analysis_failure(
            trajectory,
            input_digest=input_digest,
            judge_model=judge_model,
            agent_model=agent_model,
            judge_fingerprint=judge_fingerprint,
            error=error,
        )
    report = report.model_copy(update={"deepeval": analysis})

    execution_status = (
        report.trial.status.value if report.trial is not None else "completed"
    )
    try:
        payload = build_opik_trace_payload(
            run_id=request.manifest.run_id,
            task_id=report.task_result.task_id,
            attempt=report.task_result.attempt,
            commit_sha=request.manifest.agent_code_sha,
            profile_fingerprint=request.manifest.profile_fingerprint,
            trajectory=trajectory,
            analysis=analysis,
            task_result=report.task_result,
            patch_sha256=report.task_result.patch_sha256,
            execution_status=execution_status,
            started_at=report.task_result.started_at,
            finished_at=report.task_result.finished_at,
        )
    except Exception as error:
        payload = None
        export = _opik_failure(
            report,
            trajectory,
            error=error,
        )
    else:
        assert payload is not None
        try:
            export = publish_opik_trace(
                payload,
                client=request.opik_client,
                environ=request.opik_environment,
                project_name=request.opik_project_name,
                workspace=request.opik_workspace,
                timeout_seconds=request.opik_timeout_seconds,
            )
            if not isinstance(export, OpikExportResult):
                raise ValueError("Opik publisher returned an invalid result")
            if (
                export.run_id != payload.run_id
                or export.task_id != payload.task_id
                or export.payload_digest != payload.fingerprint()
            ):
                raise ValueError("Opik publisher returned a mismatched result")
        except Exception as error:
            export = _opik_failure(
                report,
                trajectory,
                payload=payload,
                error=error,
            )
    report = report.model_copy(update={"deepeval": analysis, "opik": export})
    return report, trajectory, payload


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


def _normalize_harness_result(
    result: HarnessRecheckResult,
    *,
    task: TaskSpec,
) -> HarnessRecheckResult:
    """将 Harness instance ID 收敛回 catalog task ID。"""

    instance_id = _swebench_instance_id(task)
    if result.task_id == task.task_id:
        return result
    if result.task_id != instance_id:
        raise ValueError("Harness result task_id does not match the selected task")
    return result.model_copy(update={"task_id": task.task_id})


def _dependency_fingerprint() -> str:
    return hashlib.sha256(
        f"harbor=={HARBOR_VERSION};swebench=={SWEBENCH_VERSION};"
        f"artifact-builder=={ARTIFACT_BUILDER_VERSION};"
        f"deepeval=={DEEPEVAL_SDK_VERSION};opik=={OPIK_SDK_VERSION}".encode()
    ).hexdigest()


def _verified_input_digest(task: TaskSpec) -> str:
    """计算 worker 实际收到的公开 prompt digest。"""

    return hashlib.sha256(task.public_prompt.encode("utf-8")).hexdigest()


def _load_trajectory(
    request: VerifiedExecutionRequest,
    *,
    output_dir: Path,
    harbor_output: HarborExecutionOutput,
    task_result: TaskResult,
) -> DeepEvalTrajectory | None:
    """读取 Harbor 已复制的脱敏 trace，或使用测试/重试提供的固定投影。"""

    if request.trajectory is not None:
        return request.trajectory.model_copy(
            update={"deterministic_verdict": task_result.verdict}
        )

    root = output_dir.resolve()
    trace_path: Path | None = None
    for reference in harbor_output.result.artifact_references:
        relative = Path(reference)
        if relative.name != "harbor-trace.json":
            continue
        candidate = (root / relative).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        trace_path = candidate
        break
    if trace_path is None or not trace_path.is_file():
        return None
    try:
        payload = json.loads(trace_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    if payload.get("schema_version") != "agent-e2e/v1":
        return None
    trace_id = payload.get("trace_id")
    raw_events = payload.get("events")
    if not isinstance(trace_id, str) or not isinstance(raw_events, list):
        return None
    try:
        events = tuple(TraceEvent.model_validate(item) for item in raw_events)
    except (TypeError, ValueError):
        return None
    trajectory = build_deepeval_trajectory(
        task_id=request.task.task_id,
        trace_id=trace_id,
        trace_events=events,
    )
    return trajectory.model_copy(update={"deterministic_verdict": task_result.verdict})


def _analysis_failure(
    trajectory: DeepEvalTrajectory,
    *,
    input_digest: str,
    judge_model: str,
    agent_model: str | None,
    judge_fingerprint: str | None,
    error: Exception,
) -> DeepEvalAnalysis:
    timed_out = isinstance(error, TimeoutError)
    status = (
        DeepEvalAnalysisStatus.TIMEOUT if timed_out else DeepEvalAnalysisStatus.FAILED
    )
    failure_source = FailureSource.TIMEOUT if timed_out else FailureSource.DEEPEVAL
    reason, _ = redact_text(
        str(error) or "DeepEval analysis failed",
        max_length=320,
    )
    model, _ = redact_text(judge_model, max_length=256)
    return DeepEvalAnalysis(
        task_id=trajectory.task_id,
        status=status,
        judge_model=model or "unknown",
        input_digest=input_digest,
        trajectory_digest=trajectory.trace_digest,
        agent_model=agent_model,
        judge_fingerprint=judge_fingerprint,
        failure_source=failure_source,
        reason=reason or "DeepEval analysis failed",
    )


def _judge_fingerprint(judge_model: str) -> str:
    """judge 身份指纹：SHA-256(judge 模型 + 端点)，端点只进哈希不进报告。"""

    endpoint = os.environ.get("LITELLM_API_BASE") or ""
    return hashlib.sha256(f"{judge_model}\n{endpoint}".encode()).hexdigest()


def _opik_failure(
    report: VerifiedEvaluationReport,
    trajectory: DeepEvalTrajectory,
    *,
    payload: OpikTracePayload | None = None,
    error: Exception,
) -> OpikExportResult:
    reason, _ = redact_text(
        str(error) or "Opik export failed",
        max_length=320,
    )
    return OpikExportResult(
        run_id=report.manifest.run_id,
        task_id=report.task_result.task_id,
        status=OpikExportStatus.FAILED,
        payload_digest=(
            payload.fingerprint() if payload is not None else trajectory.fingerprint()
        ),
        attempts=1,
        failure_source=FailureSource.OPIK,
        reason=reason or "Opik export failed",
    )


def _write_controlled_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value.canonical_json() + "\n", encoding="utf-8")


def verified_exit_code(report: VerifiedEvaluationReport) -> int:
    """将 trial 生命周期映射为稳定 CLI 退出码，不把失败得分当进程故障。"""

    if report.trial is not None:
        if report.trial.status is TrialExecutionStatus.SUBJECT_FAILED:
            return VERIFIED_EXIT_SUBJECT_FAILED
        if report.trial.status is TrialExecutionStatus.INFRA_FAILED:
            return VERIFIED_EXIT_INFRA_FAILED
        if report.trial.status is TrialExecutionStatus.INDETERMINATE:
            return VERIFIED_EXIT_INVALID
    if report.task_result.official:
        return (
            VERIFIED_EXIT_SUBJECT_FAILED
            if report.task_result.verdict is TaskVerdict.FAILED
            else VERIFIED_EXIT_COMPLETED
        )
    if report.task_result.verdict is TaskVerdict.INVALID:
        return VERIFIED_EXIT_INVALID
    return VERIFIED_EXIT_INFRA_FAILED


__all__ = [
    "VERIFIED_EXIT_COMPLETED",
    "VERIFIED_EXIT_INFRA_FAILED",
    "VERIFIED_EXIT_INVALID",
    "VERIFIED_EXIT_SUBJECT_FAILED",
    "VerifiedExecutionOutput",
    "VerifiedExecutionRequest",
    "run_verified_evaluation",
    "verified_exit_code",
    "write_verified_report",
]
