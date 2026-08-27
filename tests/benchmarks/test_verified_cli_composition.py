"""Verified 单题组合入口、报告和 CLI 的定向测试。"""

from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from benchmarks.agent_e2e.artifact import CommitArtifact
from benchmarks.agent_e2e.catalog import freeze_catalog
from benchmarks.agent_e2e.cli import main
from benchmarks.agent_e2e.deepeval_analysis import (
    DEEPEVAL_METRIC_NAMES,
    DeepEvalCase,
    DeepEvalMetricObservation,
)
from benchmarks.agent_e2e.harbor_runner import (
    HarborExecutionOutput,
    HarborExecutionRequest,
)
from benchmarks.agent_e2e.harness_runner import (
    HarnessExecutionOutput,
    HarnessExecutionRequest,
)
from benchmarks.agent_e2e.models import (
    AdapterStatus,
    Catalog,
    DeepEvalTrajectory,
    DeepEvalTrajectoryEvent,
    ExperimentManifest,
    ExperimentProfile,
    HarborRoutineVerifierResult,
    HarnessRecheckResult,
    ReportStatus,
    ResultValidity,
    TaskResult,
    TaskSpec,
    TaskSplit,
    TaskVerdict,
    TrialExecutionStatus,
    VerifiedEvaluationReport,
    VerifierOutcome,
    VerifierResult,
)
from benchmarks.agent_e2e.verified_runner import (
    VerifiedExecutionOutput,
    VerifiedExecutionRequest,
    run_verified_evaluation,
    verified_exit_code,
    write_verified_report,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _task() -> TaskSpec:
    return TaskSpec(
        task_id="verified-task-1",
        family="bugfix",
        split=TaskSplit.REGRESSION,
        repository="lion",
        base_revision="abcdef0",
        public_prompt="修复公开问题。",
        verifier_identity="verified/v1",
        gold_evidence_hash="a" * 64,
        difficulty=1,
        extensions={"swebench_instance_id": "swebench-task-1"},
    )


def _manifest(task: TaskSpec, *, budget_usd: float = 1.0) -> ExperimentManifest:
    profile = ExperimentProfile(
        profile_id="verified-online",
        model="test-model",
        provider="test-provider",
        prompt_version="prompt-v1",
        compression_version="compression-v1",
        tool_policy_version="tools-v1",
        seed=7,
        repeats=1,
        timeout_seconds=30,
        budget_usd=budget_usd,
        agent_code_sha="a" * 7,
        credential_env_vars=("TEST_PROVIDER_KEY",) if budget_usd else (),
    )
    catalog = Catalog(catalog_id="verified", catalog_version="v1", tasks=(task,))
    return ExperimentManifest(
        run_id="verified-run-1",
        agent_code_sha=profile.agent_code_sha,
        evaluator_code_sha="e" * 7,
        catalog=freeze_catalog(catalog),
        profile=profile,
        profile_fingerprint=profile.fingerprint(),
        task_ids=(task.task_id,),
        seed=profile.seed,
        repeats=profile.repeats,
        timeout_seconds=profile.timeout_seconds,
        budget_usd=profile.budget_usd,
        platform="linux-docker",
        verifier_image_digest="sha256:" + "b" * 64,
    )


def _trajectory(task_id: str) -> DeepEvalTrajectory:
    start = datetime(2026, 8, 27, 1, 0, tzinfo=UTC)
    events = (
        DeepEvalTrajectoryEvent(
            sequence=1,
            event_type="PlanCreated",
            payload_digest=_digest("plan"),
            started_at=start,
            finished_at=start + timedelta(seconds=1),
        ),
        DeepEvalTrajectoryEvent(
            sequence=2,
            event_type="ToolExecution",
            payload_digest=_digest("tool-result"),
            tool_name="read_file",
            argument_digest=_digest("arguments"),
            workspace_fingerprint=_digest("workspace"),
            started_at=start + timedelta(seconds=1),
            finished_at=start + timedelta(seconds=3),
        ),
    )
    return DeepEvalTrajectory(
        task_id=task_id,
        trace_id="trace-1",
        trace_digest=_digest("trace"),
        events=events,
    )


class _FakeArtifactBuilder:
    def __init__(self, order: list[str]) -> None:
        self.order = order

    def build(self, commit_sha: str, output_dir: Path) -> CommitArtifact:
        self.order.append("artifact")
        wheel_path = output_dir / "lion_code-0.0.0-py3-none-any.whl"
        wheel_path.parent.mkdir(parents=True, exist_ok=True)
        wheel_path.write_bytes(b"wheel")
        return CommitArtifact(
            commit_sha="a" * 40,
            tree_sha="b" * 40,
            wheel_path=wheel_path,
            wheel_sha256=_digest("wheel"),
            wheel_size_bytes=5,
            source_tree_sha256="c" * 64,
            repository_fingerprint="d" * 64,
            python_version="3.12.10",
            platform="linux",
        )


class _FakeHarborRunner:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.calls = 0
        self.patch_sha256 = _digest("patch")

    def run(self, request: HarborExecutionRequest) -> HarborExecutionOutput:
        self.order.append("harbor")
        self.calls += 1
        output_dir = request.output_dir
        patch_path = output_dir / "artifacts" / "lion.patch"
        patch_path.parent.mkdir(parents=True, exist_ok=True)
        patch_path.write_bytes(b"patch")
        return HarborExecutionOutput(
            result=HarborRoutineVerifierResult(
                task_id=request.task.task_id,
                job_id="job-1",
                status=AdapterStatus.COMPLETED,
                execution_status=TrialExecutionStatus.COMPLETED,
                verifier_outcome=VerifierOutcome.PASSED,
                reward=0.75,
                patch_sha256=self.patch_sha256,
                patch_applied=True,
                output_digest="h" * 64,
                command_summary="fake Harbor verifier",
                wall_time_seconds=1.25,
            ),
            patch_path=patch_path,
        )


class _FakeHarnessRunner:
    def __init__(self, order: list[str], expected_patch_sha256: str) -> None:
        self.order = order
        self.expected_patch_sha256 = expected_patch_sha256
        self.calls = 0

    def run(self, request: HarnessExecutionRequest) -> HarnessExecutionOutput:
        self.order.append("harness")
        self.calls += 1
        if request.patch_sha256 != self.expected_patch_sha256:
            raise AssertionError("Harness did not receive Harbor patch digest")
        return HarnessExecutionOutput(
            result=HarnessRecheckResult(
                task_id=request.instance_id,
                status=AdapterStatus.COMPLETED,
                resolved=True,
                patch_sha256=request.patch_sha256,
                output_digest="f" * 64,
                evaluator_revision="swebench-5.0.1",
                image_digest="sha256:" + "b" * 64,
            )
        )


class _FakeJudge:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.calls: list[str] = []

    def evaluate_metric(
        self,
        *,
        metric_name: str,
        case: DeepEvalCase,
    ) -> DeepEvalMetricObservation:
        self.order.append(f"deepeval:{metric_name}")
        self.calls.append(metric_name)
        return DeepEvalMetricObservation(
            name=metric_name,
            score=0.8,
            reason="safe score",
            model="fake-judge",
            input_digest=case.input_digest,
        )


class _FakeSpan:
    def __init__(self, span_id: str) -> None:
        self.id = span_id


class _FakeTrace:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.id = "trace-cloud-1"
        self.span_calls: list[dict[str, object]] = []

    def span(self, **kwargs: object) -> _FakeSpan:
        self.span_calls.append(kwargs)
        return _FakeSpan(f"cloud-span-{len(self.span_calls)}")

    def log_feedback_score(self, **kwargs: object) -> None:
        del kwargs


class _FakeOpikClient:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.trace_object = _FakeTrace(order)
        self.flush_calls: list[float] = []

    def trace(self, **kwargs: object) -> _FakeTrace:
        del kwargs
        self.order.append("opik")
        return self.trace_object

    def flush(self, *, timeout: float) -> bool:
        self.flush_calls.append(timeout)
        self.order.append("opik-flush")
        return True


def _blocked_report(
    manifest: ExperimentManifest, task: TaskSpec
) -> VerifiedEvaluationReport:
    return VerifiedEvaluationReport(
        manifest=manifest,
        task_result=TaskResult(
            task_id=task.task_id,
            attempt=1,
            verdict=TaskVerdict.BLOCKED,
            validity=ResultValidity.BLOCKED,
            invalid_reason="fixture blocked",
        ),
        status=ReportStatus.BLOCKED,
    )


class TestVerifiedComposition(unittest.TestCase):
    def test_single_chain_orders_stages_and_writes_four_part_report(self) -> None:
        task = _task()
        manifest = _manifest(task)
        order: list[str] = []
        artifact_builder = _FakeArtifactBuilder(order)
        harbor_runner = _FakeHarborRunner(order)
        harness_runner = _FakeHarnessRunner(order, harbor_runner.patch_sha256)
        judge = _FakeJudge(order)
        opik_client = _FakeOpikClient(order)

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            execution = run_verified_evaluation(
                VerifiedExecutionRequest(
                    repository_root=output_dir,
                    commit_sha="a" * 40,
                    manifest=manifest,
                    task=task,
                    output_dir=output_dir / "run",
                    python_executable="python",
                    harness_python="python",
                    trajectory=_trajectory(task.task_id),
                    deepeval_judge=judge,
                    opik_client=opik_client,
                    opik_workspace="workspace-1",
                    opik_project_name="project-1",
                ),
                artifact_builder=artifact_builder,
                harbor_runner=harbor_runner,
                harness_runner=harness_runner,
            )
            json_path, markdown_path = write_verified_report(
                execution.report,
                output_dir / "run",
            )

            self.assertEqual(order[:3], ["artifact", "harbor", "harness"])
            self.assertTrue(
                all(order.index(item) > order.index("harness") for item in order[3:])
            )
            self.assertEqual(harbor_runner.calls, 1)
            self.assertEqual(harness_runner.calls, 1)
            self.assertEqual(judge.calls, list(DEEPEVAL_METRIC_NAMES))
            self.assertTrue(execution.report.task_result.official)
            self.assertEqual(execution.report.task_result.verdict, TaskVerdict.PASSED)
            self.assertIsNotNone(execution.report.deepeval)
            self.assertIsNotNone(execution.report.opik)
            assert execution.report.deepeval is not None
            assert execution.report.opik is not None
            self.assertEqual(execution.report.deepeval.status.value, "completed")
            self.assertEqual(
                execution.report.deepeval.input_digest,
                _digest(task.public_prompt),
            )
            self.assertEqual(execution.report.opik.status.value, "exported")
            self.assertEqual(execution.report.opik.trace_id, "trace-cloud-1")
            self.assertTrue(
                (
                    output_dir / "run" / "artifacts" / "deepeval-trajectory.json"
                ).is_file()
            )
            self.assertTrue(
                (output_dir / "run" / "artifacts" / "deepeval-analysis.json").is_file()
            )
            self.assertTrue(
                (output_dir / "run" / "artifacts" / "opik-payload.json").is_file()
            )
            self.assertEqual(
                type(execution.report)
                .model_validate_json(json_path.read_text(encoding="utf-8"))
                .task_result,
                execution.report.task_result,
            )
            markdown = markdown_path.read_text(encoding="utf-8")
            self.assertIn("Harbor", markdown)
            self.assertIn("官方 Harness", markdown)
            self.assertIn("DeepEval", markdown)
            self.assertIn("Opik Cloud", markdown)

    def test_post_processing_failures_keep_official_result_and_redact_reason(
        self,
    ) -> None:
        task = _task()
        manifest = _manifest(task)
        order: list[str] = []
        harbor_runner = _FakeHarborRunner(order)
        harness_runner = _FakeHarnessRunner(order, harbor_runner.patch_sha256)
        trajectory = _trajectory(task.task_id)

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            request = VerifiedExecutionRequest(
                repository_root=output_dir,
                commit_sha="a" * 40,
                manifest=manifest,
                task=task,
                output_dir=output_dir / "run",
                python_executable="python",
                harness_python="python",
                trajectory=trajectory,
            )
            with (
                patch(
                    "benchmarks.agent_e2e.verified_runner.analyze_verified_report",
                    side_effect=RuntimeError("api_key=secret-value"),
                ),
                patch(
                    "benchmarks.agent_e2e.verified_runner.publish_opik_trace",
                    side_effect=RuntimeError("token=secret-value"),
                ),
            ):
                execution = run_verified_evaluation(
                    request,
                    artifact_builder=_FakeArtifactBuilder(order),
                    harbor_runner=harbor_runner,
                    harness_runner=harness_runner,
                )

            self.assertTrue(execution.report.task_result.official)
            self.assertEqual(execution.report.task_result.verdict, TaskVerdict.PASSED)
            self.assertIsNotNone(execution.report.deepeval)
            self.assertIsNotNone(execution.report.opik)
            assert execution.report.deepeval is not None
            assert execution.report.opik is not None
            self.assertEqual(execution.report.deepeval.status.value, "failed")
            self.assertEqual(execution.report.opik.status.value, "failed")
            serialized = execution.report.canonical_json()
            self.assertNotIn("secret-value", serialized)
            self.assertEqual(harbor_runner.calls, 1)
            self.assertEqual(harness_runner.calls, 1)


class TestVerifiedCli(unittest.TestCase):
    def test_official_subject_failure_has_subject_exit_code(self) -> None:
        task = _task()
        manifest = _manifest(task)
        report = VerifiedEvaluationReport(
            manifest=manifest,
            task_result=TaskResult(
                task_id=task.task_id,
                attempt=1,
                verdict=TaskVerdict.FAILED,
                validity=ResultValidity.VALID,
                official=True,
                patch_sha256="c" * 64,
                verifier=VerifierResult(
                    outcome=VerifierOutcome.FAILED,
                    command_summary="official Harness",
                    exit_code=1,
                    output_digest="d" * 64,
                ),
            ),
            status=ReportStatus.OFFICIAL,
        )

        self.assertEqual(verified_exit_code(report), 1)

    def test_verified_run_writes_report_and_returns_infra_exit_code(self) -> None:
        task = _task()
        manifest = _manifest(task, budget_usd=0)
        execution = VerifiedExecutionOutput(report=_blocked_report(manifest, task))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            catalog_path = root / "catalog.json"
            manifest_path = root / "manifest.json"
            output_dir = root / "output"
            catalog_path.write_text(
                Catalog(
                    catalog_id="verified", catalog_version="v1", tasks=(task,)
                ).canonical_json(),
                encoding="utf-8",
            )
            manifest_path.write_text(manifest.canonical_json(), encoding="utf-8")
            captured: list[VerifiedExecutionRequest] = []

            def fake_run(request: VerifiedExecutionRequest) -> VerifiedExecutionOutput:
                captured.append(request)
                return execution

            stdout = io.StringIO()
            with (
                patch(
                    "benchmarks.agent_e2e.cli.run_verified_evaluation",
                    side_effect=fake_run,
                ),
                redirect_stdout(stdout),
            ):
                exit_code = main(
                    [
                        "verified-run",
                        "--catalog",
                        str(catalog_path),
                        "--manifest",
                        str(manifest_path),
                        "--task-id",
                        task.task_id,
                        "--commit",
                        "a" * 40,
                        "--run-id",
                        manifest.run_id,
                        "--output-dir",
                        str(output_dir),
                    ]
                )

            payload = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 2)
            self.assertEqual(payload["status"], "infra_failed")
            self.assertTrue(Path(payload["report_json"]).is_file())
            self.assertTrue(Path(payload["report_markdown"]).is_file())
            self.assertEqual(len(captured), 1)
            self.assertEqual(captured[0].commit_sha, "a" * 40)


if __name__ == "__main__":
    unittest.main()
