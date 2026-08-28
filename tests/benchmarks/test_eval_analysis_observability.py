"""DeepEval/Opik 离线分析与宿主发布的边界测试。"""

from __future__ import annotations

import hashlib
import os
import unittest
from datetime import UTC, datetime, timedelta

from benchmarks.agent_e2e.catalog import freeze_catalog
from benchmarks.agent_e2e.deepeval_analysis import (
    DEEPEVAL_METRIC_NAMES,
    DeepEvalMetricObservation,
    DeepEvalTelemetryError,
    analyze_deepeval_case,
    analyze_verified_report,
    build_deepeval_trajectory,
)
from benchmarks.agent_e2e.models import (
    Catalog,
    DeepEvalAnalysisStatus,
    DeepEvalCase,
    DeepEvalTrajectory,
    DeepEvalTrajectoryEvent,
    ExperimentManifest,
    ExperimentProfile,
    FailureSource,
    OpikExportStatus,
    ReportStatus,
    ResultValidity,
    TaskResult,
    TaskSpec,
    TaskSplit,
    TaskVerdict,
    VerifiedEvaluationReport,
)
from benchmarks.agent_e2e.opik_export import (
    build_opik_trace_payload,
    publish_opik_trace,
    retry_opik_export,
)
from benchmarks.agent_e2e.trace import TraceEvent


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _trajectory() -> DeepEvalTrajectory:
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
        DeepEvalTrajectoryEvent(
            sequence=3,
            event_type="ModelResponse",
            payload_digest=_digest("model-result"),
            started_at=start + timedelta(seconds=3),
            finished_at=start + timedelta(seconds=4),
        ),
    )
    return DeepEvalTrajectory(
        task_id="verified-task-1",
        trace_id="trace-1",
        trace_digest=_digest("trace"),
        events=events,
        deterministic_verdict=TaskVerdict.PASSED,
    )


def _case() -> DeepEvalCase:
    trajectory = _trajectory()
    return DeepEvalCase(
        task_id=trajectory.task_id,
        input_digest=_digest("input"),
        trajectory=trajectory,
        expected_verdict=TaskVerdict.PASSED,
    )


def _trace_event(
    sequence: int,
    event_type: str,
    *,
    tool_name: str | None = None,
    started_at: datetime | None = None,
) -> TraceEvent:
    return TraceEvent(
        sequence=sequence,
        event_type=event_type,
        summary="controlled summary",
        payload_digest=_digest(f"{event_type}-{sequence}"),
        tool_name=tool_name,
        started_at=started_at,
        finished_at=started_at,
    )


class _FakeJudge:
    def __init__(self, outcomes: dict[str, object]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    def evaluate_metric(
        self,
        *,
        metric_name: str,
        case: DeepEvalCase,
    ) -> DeepEvalMetricObservation:
        self.calls.append(metric_name)
        outcome = self.outcomes[metric_name]
        if isinstance(outcome, BaseException):
            raise outcome
        return DeepEvalMetricObservation(
            name=metric_name,
            score=float(outcome),
            reason="safe score",
            model="fake-judge",
            input_digest=case.input_digest,
        )


class _CyclingJudge:
    """按调用顺序轮换分数/异常的 judge，用于采样聚合断言。"""

    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.index = 0
        self.calls: list[str] = []

    def evaluate_metric(
        self,
        *,
        metric_name: str,
        case: DeepEvalCase,
    ) -> DeepEvalMetricObservation:
        self.calls.append(metric_name)
        outcome = self.outcomes[self.index % len(self.outcomes)]
        self.index += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return DeepEvalMetricObservation(
            name=metric_name,
            score=float(outcome),
            reason="safe score",
            model="fake-judge",
            input_digest=case.input_digest,
        )


class _FakeSpan:
    def __init__(self, span_id: str) -> None:
        self.id = span_id


class _FakeTrace:
    def __init__(self) -> None:
        self.id = "trace-cloud-1"
        self.span_calls: list[dict[str, object]] = []
        self.feedback_calls: list[dict[str, object]] = []

    def span(self, **kwargs: object) -> _FakeSpan:
        self.span_calls.append(kwargs)
        return _FakeSpan(f"cloud-span-{len(self.span_calls)}")

    def log_feedback_score(self, **kwargs: object) -> None:
        self.feedback_calls.append(kwargs)


class _FakeOpikClient:
    def __init__(self, *, flush_result: bool = True) -> None:
        self.flush_result = flush_result
        self.trace_calls: list[dict[str, object]] = []
        self.flush_calls: list[float] = []
        self.trace_object = _FakeTrace()

    def trace(self, **kwargs: object) -> _FakeTrace:
        self.trace_calls.append(kwargs)
        return self.trace_object

    def flush(self, *, timeout: float) -> bool:
        self.flush_calls.append(timeout)
        return self.flush_result


def _report() -> VerifiedEvaluationReport:
    task = TaskSpec(
        task_id="verified-task-1",
        family="bugfix",
        split=TaskSplit.REGRESSION,
        repository="lion",
        base_revision="abcdef0",
        public_prompt="公开任务",
        verifier_identity="verified/v1",
        gold_evidence_hash="a" * 64,
        difficulty=1,
    )
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
        agent_code_sha="abcdef0",
    )
    catalog = freeze_catalog(
        Catalog(catalog_id="c", catalog_version="v1", tasks=(task,))
    )
    manifest = ExperimentManifest(
        run_id="run-1",
        agent_code_sha="abcdef0",
        evaluator_code_sha="1234567",
        catalog=catalog,
        profile=profile,
        profile_fingerprint=profile.fingerprint(),
        task_ids=(task.task_id,),
        seed=1,
        repeats=1,
        timeout_seconds=10,
        budget_usd=0,
        platform="windows",
    )
    return VerifiedEvaluationReport(
        manifest=manifest,
        task_result=TaskResult(
            task_id=task.task_id,
            attempt=1,
            verdict=TaskVerdict.BLOCKED,
            validity=ResultValidity.OFFLINE_ONLY,
            invalid_reason="fixture only",
        ),
        status=ReportStatus.BLOCKED,
    )


class TestDeepEvalAnalysis(unittest.TestCase):
    def test_fixed_metrics_complete_and_share_one_case(self) -> None:
        case = _case()
        judge = _FakeJudge(dict.fromkeys(DEEPEVAL_METRIC_NAMES, 0.75))
        analysis = analyze_deepeval_case(
            case,
            judge_model="fake-judge",
            judge=judge,
            timeout_seconds=None,
        )
        self.assertEqual(analysis.status, DeepEvalAnalysisStatus.COMPLETED)
        self.assertEqual(
            tuple(metric.name for metric in analysis.metrics),
            DEEPEVAL_METRIC_NAMES,
        )
        self.assertEqual(  # 指标外层、采样内层
            judge.calls,
            [name for name in DEEPEVAL_METRIC_NAMES for _ in range(3)],
        )
        self.assertTrue(
            all(metric.input_digest == case.input_digest for metric in analysis.metrics)
        )
        # 阈值对照与门禁:全过(0.75 >= 0.5) → threshold_met 全 True,
        # score_gate 通过(3/3)。
        self.assertTrue(all(metric.threshold == 0.5 for metric in analysis.metrics))
        self.assertTrue(
            all(metric.threshold_met is True for metric in analysis.metrics)
        )
        # 采样聚合:默认 3 次采样,同分样本均值=极值。
        self.assertTrue(all(metric.samples == 3 for metric in analysis.metrics))
        self.assertTrue(
            all(
                metric.score_min == 0.75 and metric.score_max == 0.75
                for metric in analysis.metrics
            )
        )
        self.assertIsNotNone(analysis.score_gate)
        assert analysis.score_gate is not None
        self.assertTrue(analysis.score_gate.passed)
        self.assertEqual(
            (analysis.score_gate.passed_metrics, analysis.score_gate.evaluated_metrics),
            (3, 3),
        )

    def test_score_gate_partial_threshold_failure(self) -> None:
        case = _case()
        judge = _FakeJudge(
            {
                DEEPEVAL_METRIC_NAMES[0]: 0.4,
                DEEPEVAL_METRIC_NAMES[1]: 0.75,
                DEEPEVAL_METRIC_NAMES[2]: 0.6,
            }
        )
        analysis = analyze_deepeval_case(
            case,
            judge_model="fake-judge",
            judge=judge,
            timeout_seconds=None,
        )
        self.assertEqual(analysis.status, DeepEvalAnalysisStatus.COMPLETED)
        self.assertEqual(
            [m.threshold_met for m in analysis.metrics], [False, True, True]
        )
        self.assertIsNotNone(analysis.score_gate)
        assert analysis.score_gate is not None
        self.assertFalse(analysis.score_gate.passed)
        self.assertEqual(
            (analysis.score_gate.passed_metrics, analysis.score_gate.evaluated_metrics),
            (2, 3),
        )
        self.assertIn("2 项达阈值", analysis.score_gate.reason)

    def test_score_gate_none_when_no_completed_scores(self) -> None:
        case = _case()
        judge = _FakeJudge(
            dict.fromkeys(DEEPEVAL_METRIC_NAMES, TimeoutError("judge timeout"))
        )
        analysis = analyze_deepeval_case(
            case,
            judge_model="fake-judge",
            judge=judge,
            timeout_seconds=None,
        )
        self.assertEqual(analysis.status, DeepEvalAnalysisStatus.TIMEOUT)
        self.assertIsNone(analysis.score_gate)
        self.assertTrue(
            all(metric.threshold_met is False for metric in analysis.metrics)
        )

    def test_sampling_aggregates_mean_and_range(self) -> None:
        case = _case()
        judge = _CyclingJudge([0.4, 0.8, 0.6])
        analysis = analyze_deepeval_case(
            case,
            judge_model="fake-judge",
            judge=judge,
            timeout_seconds=None,
        )
        self.assertEqual(analysis.status, DeepEvalAnalysisStatus.COMPLETED)
        for metric in analysis.metrics:
            self.assertEqual(metric.samples, 3)
            self.assertAlmostEqual(metric.score, 0.6)
            self.assertEqual(metric.score_min, 0.4)
            self.assertEqual(metric.score_max, 0.8)
            self.assertTrue(metric.threshold_met)  # 均值 0.6 >= 0.5

    def test_sampling_partial_failure_annotates_reason(self) -> None:
        case = _case()
        judge = _CyclingJudge([0.8, RuntimeError("boom"), 0.6])
        analysis = analyze_deepeval_case(
            case,
            judge_model="fake-judge",
            judge=judge,
            timeout_seconds=None,
        )
        self.assertEqual(analysis.status, DeepEvalAnalysisStatus.COMPLETED)
        for metric in analysis.metrics:
            self.assertEqual(metric.samples, 3)
            self.assertAlmostEqual(metric.score, 0.7)  # (0.8+0.6)/2
            self.assertEqual(metric.score_min, 0.6)
            self.assertEqual(metric.score_max, 0.8)
            self.assertIn("1 次采样失败", metric.reason or "")

    def test_sampling_all_failed_keeps_failure_semantics(self) -> None:
        case = _case()
        judge = _CyclingJudge([TimeoutError("slice is gone")])
        analysis = analyze_deepeval_case(
            case,
            judge_model="fake-judge",
            judge=judge,
            timeout_seconds=None,
        )
        self.assertEqual(analysis.status, DeepEvalAnalysisStatus.TIMEOUT)
        for metric in analysis.metrics:
            self.assertEqual(metric.samples, 3)
            self.assertIsNone(metric.score)
            self.assertIsNone(metric.score_min)
            self.assertFalse(metric.threshold_met)

    def test_single_sample_keeps_legacy_semantics(self) -> None:
        case = _case()
        judge = _FakeJudge(dict.fromkeys(DEEPEVAL_METRIC_NAMES, 0.75))
        analysis = analyze_deepeval_case(
            case,
            judge_model="fake-judge",
            judge=judge,
            timeout_seconds=None,
            judge_samples=1,
        )
        self.assertEqual(judge.calls, list(DEEPEVAL_METRIC_NAMES))
        for metric in analysis.metrics:
            self.assertEqual(metric.samples, 1)
            self.assertIsNone(metric.score_min)
            self.assertIsNone(metric.score_max)
            self.assertEqual(metric.score, 0.75)

    def test_partial_metric_failure_keeps_other_scores_and_redacts_reason(self) -> None:
        case = _case()
        judge = _FakeJudge(
            {
                DEEPEVAL_METRIC_NAMES[0]: 0.8,
                DEEPEVAL_METRIC_NAMES[1]: RuntimeError("api_key=sk-not-persisted"),
                DEEPEVAL_METRIC_NAMES[2]: 0.6,
            }
        )
        analysis = analyze_deepeval_case(
            case,
            judge_model="fake-judge",
            judge=judge,
            timeout_seconds=None,
        )
        self.assertEqual(analysis.status, DeepEvalAnalysisStatus.PARTIAL)
        self.assertEqual(analysis.failure_source, FailureSource.DEEPEVAL)
        self.assertAlmostEqual(analysis.metrics[0].score, 0.8)
        self.assertIsNone(analysis.metrics[1].score)
        self.assertNotIn("sk-not-persisted", analysis.canonical_json())
        # 失败指标仍带阈值但不可达(score 恒 None → threshold_met False)。
        self.assertEqual(analysis.metrics[1].threshold, 0.5)
        self.assertFalse(analysis.metrics[1].threshold_met)
        # score_gate 只评估已评分指标:失败指标不计入,其余两项 0.8/0.6 均达阈值。
        self.assertIsNotNone(analysis.score_gate)
        assert analysis.score_gate is not None
        self.assertTrue(analysis.score_gate.passed)
        self.assertEqual(analysis.score_gate.evaluated_metrics, 2)
        self.assertEqual(analysis.score_gate.passed_metrics, 2)

    def test_analysis_records_agent_model_and_judge_fingerprint(self) -> None:
        case = _case()
        report = _report()
        updated = analyze_verified_report(
            report,
            input_digest=case.input_digest,
            trajectory=case.trajectory,
            judge_model="judge-model-1",
            judge=_FakeJudge(dict.fromkeys(DEEPEVAL_METRIC_NAMES, 0.5)),
            timeout_seconds=None,
            agent_model="agent-model-2",
            judge_fingerprint="f" * 64,
        )
        self.assertEqual(updated.deepeval.judge_model, "judge-model-1")
        self.assertEqual(updated.deepeval.agent_model, "agent-model-2")
        self.assertEqual(updated.deepeval.judge_fingerprint, "f" * 64)

    def test_timeout_is_typed_and_does_not_change_report_task_result(self) -> None:
        case = _case()
        judge = _FakeJudge(
            dict.fromkeys(
                DEEPEVAL_METRIC_NAMES,
                TimeoutError("judge timeout"),
            )
        )
        analysis = analyze_deepeval_case(
            case,
            judge_model="fake-judge",
            judge=judge,
            timeout_seconds=None,
        )
        self.assertEqual(analysis.status, DeepEvalAnalysisStatus.TIMEOUT)
        report = _report()
        updated = analyze_verified_report(
            report,
            input_digest=case.input_digest,
            trajectory=case.trajectory,
            judge_model="fake-judge",
            judge=_FakeJudge(dict.fromkeys(DEEPEVAL_METRIC_NAMES, 0.5)),
            timeout_seconds=None,
        )
        self.assertEqual(updated.task_result.verdict, report.task_result.verdict)
        self.assertIsNotNone(updated.deepeval)

    def test_confident_api_key_set_rejects_analysis(self) -> None:
        case = _case()
        report = _report()
        os.environ["CONFIDENT_API_KEY"] = "sk-test-key"
        try:
            with self.assertRaises(DeepEvalTelemetryError):
                analyze_verified_report(
                    report,
                    input_digest=case.input_digest,
                    trajectory=case.trajectory,
                    judge_model="fake-judge",
                    judge=_FakeJudge(dict.fromkeys(DEEPEVAL_METRIC_NAMES, 0.5)),
                    timeout_seconds=None,
                )
        finally:
            os.environ.pop("CONFIDENT_API_KEY", None)

    @unittest.skipIf(
        "CONFIDENT_API_KEY" in os.environ, "requires unset CONFIDENT_API_KEY"
    )
    def test_analysis_records_telemetry_off_when_unconfigured(self) -> None:
        case = _case()
        report = _report()
        updated = analyze_verified_report(
            report,
            input_digest=case.input_digest,
            trajectory=case.trajectory,
            judge_model="fake-judge",
            judge=_FakeJudge(dict.fromkeys(DEEPEVAL_METRIC_NAMES, 0.75)),
            timeout_seconds=None,
        )
        self.assertEqual(updated.deepeval.status, DeepEvalAnalysisStatus.COMPLETED)
        self.assertEqual(updated.deepeval.extensions.get("telemetry"), "off")

    def test_trajectory_projection_filters_message_update_noise(self) -> None:
        start = datetime(2026, 8, 27, 2, 0, tzinfo=UTC)
        snapshot = _trace_event(1, "message_update")
        tool_end = _trace_event(
            3,
            "tool_execution_end",
            tool_name="run_shell",
            started_at=start,
        )
        snapshot2 = _trace_event(2, "message_update")
        message_end = _trace_event(4, "message_end", started_at=start)

        trajectory = build_deepeval_trajectory(
            task_id="verified-task-1",
            trace_id="trace-filtered",
            trace_events=(snapshot, snapshot2, tool_end, message_end),
        )
        self.assertEqual(
            [event.event_type for event in trajectory.events],
            ["tool_execution_end", "message_end"],
        )
        self.assertEqual(trajectory.events[0].tool_name, "run_shell")
        self.assertEqual(trajectory.events[0].started_at, start)


class TestOpikPublisher(unittest.TestCase):
    def test_fake_client_receives_redacted_tree_timestamps_feedback_and_flush(
        self,
    ) -> None:
        case = _case()
        analysis = analyze_deepeval_case(
            case,
            judge_model="fake-judge",
            judge=_FakeJudge(dict.fromkeys(DEEPEVAL_METRIC_NAMES, 0.75)),
            timeout_seconds=None,
        )
        payload = build_opik_trace_payload(
            run_id="run-1",
            task_id=case.task_id,
            attempt=1,
            commit_sha="abcdef0",
            profile_fingerprint="b" * 64,
            trajectory=case.trajectory,
            analysis=analysis,
            task_result=_report().task_result,
            patch_sha256="c" * 64,
            started_at=datetime(2026, 8, 27, 1, 0, tzinfo=UTC),
            finished_at=datetime(2026, 8, 27, 1, 0, 5, tzinfo=UTC),
        )
        client = _FakeOpikClient()
        result = publish_opik_trace(
            payload,
            client=client,
            workspace="workspace-1",
            project_name="project-1",
            timeout_seconds=3,
        )
        self.assertEqual(result.status, OpikExportStatus.EXPORTED)
        self.assertEqual(result.trace_id, "trace-cloud-1")
        self.assertEqual(len(client.trace_object.span_calls), len(payload.spans))
        self.assertIsNone(client.trace_object.span_calls[0]["parent_span_id"])
        self.assertEqual(
            client.trace_object.span_calls[1]["parent_span_id"],
            "cloud-span-1",
        )
        self.assertEqual(
            client.trace_object.span_calls[1]["start_time"],
            payload.spans[1].started_at,
        )
        self.assertEqual(
            {item["name"] for item in client.trace_object.feedback_calls},
            set(DEEPEVAL_METRIC_NAMES),
        )
        self.assertEqual(client.flush_calls, [3])
        serialized = payload.canonical_json()
        self.assertNotIn("private", serialized)
        self.assertNotIn("api_key", serialized)

    def test_flush_failure_can_retry_same_payload_without_agent_execution(self) -> None:
        case = _case()
        payload = build_opik_trace_payload(
            run_id="run-1",
            task_id=case.task_id,
            attempt=1,
            commit_sha="abcdef0",
            profile_fingerprint="b" * 64,
            trajectory=case.trajectory,
        )
        failed = publish_opik_trace(
            payload,
            client=_FakeOpikClient(flush_result=False),
            workspace="workspace-1",
            project_name="project-1",
        )
        self.assertEqual(failed.status, OpikExportStatus.TIMEOUT)
        retried = retry_opik_export(
            payload,
            previous_result=failed,
            client=_FakeOpikClient(),
            workspace="workspace-1",
            project_name="project-1",
        )
        self.assertEqual(retried.status, OpikExportStatus.EXPORTED)
        self.assertEqual(retried.attempts, 2)

    def test_missing_host_credentials_are_unavailable_without_persisting_a_key(
        self,
    ) -> None:
        case = _case()
        payload = build_opik_trace_payload(
            run_id="run-1",
            task_id=case.task_id,
            attempt=1,
            commit_sha="abcdef0",
            profile_fingerprint="b" * 64,
            trajectory=case.trajectory,
        )
        result = publish_opik_trace(payload, environ={})
        self.assertEqual(result.status, OpikExportStatus.UNAVAILABLE)
        self.assertNotIn("secret", result.canonical_json())


if __name__ == "__main__":
    unittest.main()
