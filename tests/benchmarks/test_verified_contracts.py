"""Verified 结果契约与四类离线 fixture parser 的边界测试。"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from benchmarks.agent_e2e.deepeval_analysis import (
    DeepEvalSchemaError,
    build_deepeval_trajectory,
    parse_deepeval_analysis,
)
from benchmarks.agent_e2e.fixtures import (
    AGENT_CODE_SHA,
    EVALUATOR_CODE_SHA,
    make_task,
)
from benchmarks.agent_e2e.harness import (
    HarnessSchemaError,
    harness_result_to_task_result,
    map_harness_status,
    parse_harness_result,
)
from benchmarks.agent_e2e.models import (
    AdapterStatus,
    DeepEvalAnalysisStatus,
    DeepEvalMetricResult,
    DeepEvalScoreGate,
    ExperimentManifest,
    ExperimentProfile,
    FailureSource,
    HarborRoutineVerifierResult,
    OpikExportStatus,
    OpikSpan,
    OpikTracePayload,
    ReportStatus,
    ResultValidity,
    TaskResult,
    TaskSpec,
    TaskVerdict,
    TrialExecution,
    TrialExecutionStatus,
    VerifiedEvaluationReport,
    VerifiedProvenance,
    VerifierOutcome,
)
from benchmarks.agent_e2e.opik_export import (
    OpikExportSchemaError,
    parse_opik_export_result,
)
from benchmarks.agent_e2e.swebench_verified import (
    HarborPathBoundaryError,
    HarborResultError,
    HarborSchemaError,
    map_harbor_status,
    parse_harbor_result,
)
from benchmarks.agent_e2e.trace import TraceEvent

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "agent_e2e"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _task() -> TaskSpec:
    return make_task()


def _manifest() -> ExperimentManifest:
    task = _task()
    profile = ExperimentProfile(
        profile_id="offline",
        model="fake",
        provider="fake",
        prompt_version="p1",
        compression_version="c1",
        tool_policy_version="t1",
        seed=1,
        repeats=1,
        timeout_seconds=10,
        budget_usd=0,
        agent_code_sha=AGENT_CODE_SHA,
    )
    from benchmarks.agent_e2e.catalog import freeze_catalog
    from benchmarks.agent_e2e.models import Catalog

    lock = freeze_catalog(Catalog(catalog_id="c", catalog_version="v1", tasks=(task,)))
    return ExperimentManifest(
        run_id="run-1",
        agent_code_sha=AGENT_CODE_SHA,
        evaluator_code_sha=EVALUATOR_CODE_SHA,
        catalog=lock,
        profile=profile,
        profile_fingerprint=profile.fingerprint(),
        task_ids=(task.task_id,),
        seed=1,
        repeats=1,
        timeout_seconds=10,
        budget_usd=0,
        platform="windows",
    )


class TestVerifiedModels(unittest.TestCase):
    def test_provenance_and_trial_round_trip_reject_dirt_and_unknown_fields(
        self,
    ) -> None:
        provenance = VerifiedProvenance(
            git_commit_sha="a" * 40,
            git_tree_sha="b" * 40,
            wheel_sha256="c" * 64,
            wheel_filename="lion_code-1.0.0-py3-none-any.whl",
            wheel_size_bytes=1,
            source_tree_sha256="d" * 64,
            repository_fingerprint="e" * 64,
            python_version="3.12.10",
            platform="win32",
            builder_version="git-object-wheel/v1",
        )
        self.assertEqual(
            VerifiedProvenance.from_json(provenance.canonical_json()), provenance
        )
        with self.assertRaises(ValidationError):
            VerifiedProvenance.model_validate(
                {**provenance.model_dump(), "unexpected": True}
            )
        with self.assertRaises(ValidationError):
            VerifiedProvenance.model_validate(
                {**provenance.model_dump(), "dirty_worktree": True}
            )
        trial = TrialExecution(
            run_id="run-1",
            task_id="verified-task-1",
            attempt=1,
            status=TrialExecutionStatus.INFRA_FAILED,
            failure_source=FailureSource.HARBOR,
            reason="Harbor unavailable",
            wall_time_seconds=0,
        )
        self.assertEqual(
            TrialExecution.from_json(trial.canonical_json()).status,
            TrialExecutionStatus.INFRA_FAILED,
        )

    def test_nested_sensitive_extension_keys_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            HarborRoutineVerifierResult(
                task_id="verified-task-1",
                job_id="job-1",
                status=AdapterStatus.UNAVAILABLE,
                execution_status=TrialExecutionStatus.INFRA_FAILED,
                reason="blocked",
                extensions={"nested": [{"session_token": "secret"}]},
            )

    def test_deepeval_metric_threshold_and_score_gate_validation(self) -> None:
        # threshold 与 threshold_met 必须成对出现且一致。
        with self.assertRaises(ValidationError):
            DeepEvalMetricResult(
                name="TaskCompletionMetric",
                score=0.8,
                model="fake-judge",
                input_digest=_digest("input"),
                threshold=0.5,
            )
        with self.assertRaises(ValidationError):
            DeepEvalMetricResult(
                name="TaskCompletionMetric",
                score=0.8,
                model="fake-judge",
                input_digest=_digest("input"),
                threshold=0.5,
                threshold_met=False,
            )
        below = DeepEvalMetricResult(
            name="TaskCompletionMetric",
            score=0.4,
            model="fake-judge",
            input_digest=_digest("input"),
            threshold=0.5,
            threshold_met=False,
        )
        self.assertFalse(below.threshold_met)
        # 采样聚合:samples>1 必须带 min/max;范围必须包含均值;失败指标不能带范围。
        with self.assertRaises(ValidationError):
            DeepEvalMetricResult(
                name="TaskCompletionMetric",
                score=0.6,
                model="fake-judge",
                input_digest=_digest("input"),
                samples=3,
            )
        with self.assertRaises(ValidationError):
            DeepEvalMetricResult(
                name="TaskCompletionMetric",
                score=0.6,
                model="fake-judge",
                input_digest=_digest("input"),
                samples=3,
                score_min=0.7,
                score_max=0.8,
            )
        sampled = DeepEvalMetricResult(
            name="TaskCompletionMetric",
            score=0.6,
            model="fake-judge",
            input_digest=_digest("input"),
            samples=3,
            score_min=0.4,
            score_max=0.8,
        )
        self.assertEqual(sampled.samples, 3)
        with self.assertRaises(ValidationError):
            DeepEvalMetricResult(
                name="TaskCompletionMetric",
                score=None,
                status=AdapterStatus.FAILED,
                reason="failed",
                model="fake-judge",
                input_digest=_digest("input"),
                score_min=0.4,
                score_max=0.8,
            )
        # score_gate 结论必须与计数一致,且至少评估一个指标。
        with self.assertRaises(ValidationError):
            DeepEvalScoreGate(
                passed=True, passed_metrics=2, evaluated_metrics=3, reason="x"
            )
        with self.assertRaises(ValidationError):
            DeepEvalScoreGate(
                passed=False, passed_metrics=0, evaluated_metrics=0, reason="x"
            )
        gate = DeepEvalScoreGate(
            passed=False, passed_metrics=2, evaluated_metrics=3, reason="x"
        )
        self.assertEqual(DeepEvalScoreGate.from_json(gate.canonical_json()), gate)

    def test_verified_report_keeps_task_result_invariant(self) -> None:
        result = TaskResult(
            task_id="verified-task-1",
            attempt=1,
            verdict=TaskVerdict.BLOCKED,
            validity=ResultValidity.OFFLINE_ONLY,
            invalid_reason="fixture only",
        )
        report = VerifiedEvaluationReport(
            manifest=_manifest(),
            task_result=result,
            status=ReportStatus.BLOCKED,
        )
        restored = VerifiedEvaluationReport.from_json(report.canonical_json())
        self.assertEqual(restored.task_result.verdict, TaskVerdict.BLOCKED)

    def test_opik_payload_is_typed_and_does_not_accept_sensitive_metadata(self) -> None:
        timestamp = datetime(2026, 8, 27, tzinfo=UTC)
        payload = OpikTracePayload(
            run_id="run-1",
            task_id="verified-task-1",
            attempt=1,
            commit_sha="abcdef0",
            profile_fingerprint="a" * 64,
            spans=(
                OpikSpan(
                    span_id="span-1",
                    span_type="agent",
                    name="verified-run",
                    started_at=timestamp,
                    finished_at=timestamp,
                    status="completed",
                ),
            ),
            metadata={"run_id": "run-1"},
        )
        restored = OpikTracePayload.from_json(payload.canonical_json())
        self.assertEqual(restored.spans[0].span_type, "agent")
        with self.assertRaises(ValidationError):
            OpikTracePayload(
                run_id="run-1",
                task_id="verified-task-1",
                attempt=1,
                commit_sha="abcdef0",
                profile_fingerprint="a" * 64,
                spans=payload.spans,
                metadata={"api_key": "must not persist"},
            )


class TestVerifiedFixtures(unittest.TestCase):
    def test_harbor_fixture_maps_status_and_enforces_job_path(self) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "harbor_result.v1.json").read_text(encoding="utf-8")
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "artifacts").mkdir()
            (root / "artifacts" / "patch.diff").write_bytes(b"diff --git a/x b/x\n")
            (root / "artifacts" / "trajectory.json").write_text("{}", encoding="utf-8")
            result = parse_harbor_result(payload, job_root=root)
            with self.assertRaises(HarborResultError):
                parse_harbor_result(
                    {**payload, "patch_path": "artifacts/missing.diff"},
                    job_root=root,
                )
        self.assertEqual(result.status, AdapterStatus.COMPLETED)
        self.assertEqual(result.execution_status, TrialExecutionStatus.COMPLETED)
        self.assertEqual(result.verifier_outcome, VerifierOutcome.PASSED)
        self.assertEqual(result.artifact_references[0], "artifacts/trajectory.json")
        with self.assertRaises(HarborPathBoundaryError):
            parse_harbor_result(
                {**payload, "patch_path": "../outside.diff"},
                job_root=Path(tempfile.gettempdir()) / "job",
            )

    def test_harbor_schema_drift_and_statuses_are_explicit(self) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "harbor_result.v1.json").read_text(encoding="utf-8")
        )
        with self.assertRaises(HarborSchemaError):
            parse_harbor_result({**payload, "new_field": True})
        with self.assertRaises(HarborSchemaError):
            parse_harbor_result({**payload, "schema_version": "harbor-result/v2"})
        self.assertEqual(
            map_harbor_status("agent_error")[1], TrialExecutionStatus.SUBJECT_FAILED
        )
        self.assertEqual(
            map_harbor_status("docker_error")[1], TrialExecutionStatus.INFRA_FAILED
        )
        self.assertEqual(map_harbor_status("docker_error")[2], FailureSource.DOCKER)
        self.assertEqual(
            map_harbor_status("cancelled")[1], TrialExecutionStatus.INDETERMINATE
        )
        with self.assertRaises(HarborSchemaError):
            parse_harbor_result({**payload, "api_key": "do-not-read"})
        with self.assertRaises(HarborPathBoundaryError):
            parse_harbor_result(payload)

    def test_harness_fixture_recheck_stays_non_official_by_default(self) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "harness_result.v1.json").read_text(encoding="utf-8")
        )
        result = parse_harness_result(
            payload,
            expected_task_id="verified-task-1",
            patch_sha256="a" * 64,
        )
        self.assertEqual(result.status, AdapterStatus.COMPLETED)
        self.assertTrue(result.resolved)
        offline = harness_result_to_task_result(result, manifest=_manifest())
        self.assertFalse(offline.official)
        self.assertEqual(offline.verdict, TaskVerdict.BLOCKED)
        official = harness_result_to_task_result(
            result,
            manifest=_manifest(),
            supports_official_scores=True,
        )
        self.assertTrue(official.official)
        self.assertEqual(official.verdict, TaskVerdict.PASSED)
        with self.assertRaises(HarnessSchemaError):
            parse_harness_result({**payload, "unknown": True})
        with self.assertRaises(HarnessSchemaError):
            parse_harness_result(
                {**payload, "schema_version": "swebench-harness-result/v2"}
            )
        with self.assertRaises(HarnessSchemaError):
            parse_harness_result({**payload, "nested": {"access_token": "secret"}})
        self.assertEqual(
            map_harness_status("infra_error")[0], AdapterStatus.UNAVAILABLE
        )
        self.assertEqual(map_harness_status("error")[0], AdapterStatus.FAILED)
        self.assertEqual(map_harness_status("cancelled")[1], FailureSource.CANCELLATION)

    def test_deepeval_fixture_and_trace_projection_drop_raw_text(self) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "deepeval_result.v1.json").read_text(encoding="utf-8")
        )
        analysis = parse_deepeval_analysis(payload, expected_task_id="verified-task-1")
        self.assertEqual(analysis.status, DeepEvalAnalysisStatus.COMPLETED)
        self.assertEqual(len(analysis.metrics), 3)
        # 阈值是宿主侧策略常量:解析时按指标名补齐(1.0/0.8/0.9 均 ≥ 0.5)。
        self.assertTrue(all(metric.threshold == 0.5 for metric in analysis.metrics))
        self.assertTrue(all(metric.threshold_met for metric in analysis.metrics))
        self.assertIsNotNone(analysis.score_gate)
        assert analysis.score_gate is not None
        self.assertTrue(analysis.score_gate.passed)
        self.assertEqual(analysis.score_gate.evaluated_metrics, 3)
        # 采样字段:旧 fixture 无 samples → 默认 1;min/max 缺省。
        self.assertTrue(all(metric.samples == 1 for metric in analysis.metrics))
        self.assertTrue(all(metric.score_min is None for metric in analysis.metrics))
        # fixture 可显式携带采样信息并透传。
        sampled = parse_deepeval_analysis(
            {
                **payload,
                "metrics": [
                    {
                        **payload["metrics"][0],
                        "samples": 2,
                        "score_min": 0.9,
                        "score_max": 1.0,
                    }
                ],
            },
            expected_task_id="verified-task-1",
        )
        self.assertEqual(sampled.metrics[0].samples, 2)
        self.assertEqual(sampled.metrics[0].score_min, 0.9)
        self.assertEqual(sampled.metrics[0].score_max, 1.0)
        event = TraceEvent(
            sequence=1,
            event_type="ToolExecutionStartEvent",
            summary="private prompt must not persist",
            payload_digest=_digest("payload"),
            tool_name="read_file",
            argument_digest=_digest("arguments"),
            workspace_fingerprint=_digest("workspace"),
        )
        trajectory = build_deepeval_trajectory(
            task_id="verified-task-1",
            trace_id="trace-1",
            trace_events=(event,),
        )
        serialized = trajectory.canonical_json()
        self.assertNotIn("private prompt", serialized)
        self.assertIn("workspace_fingerprint", serialized)
        with self.assertRaises(DeepEvalSchemaError):
            parse_deepeval_analysis({**payload, "token": "secret"})
        with self.assertRaises(DeepEvalSchemaError):
            parse_deepeval_analysis({**payload, "schema_version": "deepeval-result/v2"})
        partial = parse_deepeval_analysis(
            {
                **payload,
                "status": "partial",
                "metrics": [
                    {
                        "name": "TaskCompletionMetric",
                        "score": None,
                        "status": "timeout",
                    }
                ],
            }
        )
        self.assertEqual(partial.status, DeepEvalAnalysisStatus.PARTIAL)
        self.assertEqual(partial.failure_source, FailureSource.DEEPEVAL)
        # 非 completed 指标带阈值但不可达(无分数 → threshold_met False)。
        self.assertEqual(partial.metrics[0].threshold, 0.5)
        self.assertFalse(partial.metrics[0].threshold_met)
        self.assertIsNone(partial.score_gate)
        with self.assertRaises(DeepEvalSchemaError):
            parse_deepeval_analysis(
                {
                    **payload,
                    "metrics": [payload["metrics"][0], payload["metrics"][0]],
                }
            )

    def test_opik_failure_is_independent_and_never_contains_key(self) -> None:
        payload = json.loads(
            (FIXTURE_ROOT / "opik_export_result.v1.json").read_text(encoding="utf-8")
        )
        result = parse_opik_export_result(
            payload,
            expected_run_id="run-offline-1",
            expected_task_id="verified-task-1",
        )
        self.assertEqual(result.status, OpikExportStatus.EXPORTED)
        self.assertEqual(result.trace_id, "trace-offline-1")
        self.assertIsNone(result.failure_source)
        with self.assertRaises(OpikExportSchemaError):
            parse_opik_export_result({**payload, "api_key": "secret"})
        with self.assertRaises(OpikExportSchemaError):
            parse_opik_export_result(
                {**payload, "schema_version": "opik-export-result/v2"}
            )
        failure = parse_opik_export_result(
            {
                **payload,
                "status": "timeout",
                "trace_id": None,
                "error": "network timeout",
            }
        )
        self.assertEqual(failure.status, OpikExportStatus.TIMEOUT)
        self.assertEqual(failure.failure_source, FailureSource.TIMEOUT)
        self.assertIsNone(failure.trace_id)


if __name__ == "__main__":
    unittest.main()
