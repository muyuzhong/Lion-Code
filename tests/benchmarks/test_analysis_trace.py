"""Analysis Trace 的安全投影、DeepEval 输入和边界测试。"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

from benchmarks.agent_e2e.analysis_trace import (
    AnalysisTrace,
    AnalysisTraceSchemaError,
    AnalysisTraceUnavailable,
    load_analysis_trace,
    project_analysis_trace,
)
from benchmarks.agent_e2e.deepeval_analysis import (
    DeepEvalAnalysisCase,
    DeepEvalMetricObservation,
    analyze_deepeval_case,
)
from benchmarks.agent_e2e.deepeval_metrics import DeepEvalSdkJudge
from benchmarks.agent_e2e.models import AdapterStatus
from lion_code.core.events import (
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    ToolExecutionUpdateEvent,
)
from lion_code.core.tools import AgentToolResult


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _trace(workspace: Path, *, degraded: bool = False):
    if degraded:
        command = "unknown-command --secret=not-for-persistence"
        first_tool = "read_file"
        first_args = {"file_path": "src/unrelated.py"}
    else:
        command = "python -m pytest tests/test_config.py -q --maxfail=1"
        first_tool = "read_file"
        first_args = {"file_path": "src/config.py"}
    return project_analysis_trace(
        "task-1",
        "trace-1",
        (
            ToolExecutionStartEvent(
                tool_call_id="call-1",
                tool_name=first_tool,
                args=first_args,
            ),
            ToolExecutionUpdateEvent(
                tool_call_id="call-1",
                tool_name=first_tool,
                args=first_args,
                partial_result=AgentToolResult(
                    content="private incremental output",
                ),
            ),
            ToolExecutionEndEvent(
                tool_call_id="call-1",
                tool_name=first_tool,
                result=AgentToolResult(
                    content="private stdout",
                    details={"stdout": "source line must not persist"},
                ),
                is_error=False,
            ),
            ToolExecutionStartEvent(
                tool_call_id="call-2",
                tool_name="run_shell",
                args={"command": command},
            ),
            ToolExecutionEndEvent(
                tool_call_id="call-2",
                tool_name="run_shell",
                result=AgentToolResult(
                    content="raw stderr must not persist",
                    details={
                        "exit_code": 0 if not degraded else 1,
                        "test_count": 4,
                        "error_type": None if not degraded else "ModuleNotFoundError",
                        "stdout": "raw output",
                        "stderr": "raw error",
                    },
                ),
                is_error=degraded,
            ),
        ),
        workspace=workspace,
    )


class _DirectionalJudge:
    """只根据安全投影判断方向，避免测试依赖在线 DeepEval。"""

    def evaluate_metric(
        self,
        *,
        metric_name: str,
        case: DeepEvalAnalysisCase,
    ) -> DeepEvalMetricObservation:
        calls = [
            event for event in case.analysis_trace.events if event.kind == "tool_call"
        ]
        shell = next(
            (event for event in calls if event.tool_name == "run_shell"),
            None,
        )
        good_shell = bool(
            shell
            and shell.safe_data.get("command_family") == "pytest"
            and shell.safe_data.get("target") == "tests/test_config.py"
        )
        score = 0.9 if good_shell else 0.2
        return DeepEvalMetricObservation(
            name=metric_name,
            score=score,
            reason="directional evidence [seq=1]",
            model="fake-judge",
            input_digest=case.input_digest,
            status=AdapterStatus.COMPLETED,
        )


class _ReasonJudge:
    def __init__(self, reason: str | None) -> None:
        self.reason = reason

    def evaluate_metric(self, *, metric_name: str, case: DeepEvalAnalysisCase):
        return DeepEvalMetricObservation(
            name=metric_name,
            score=0.8,
            reason=self.reason,
            model="fake-judge",
            input_digest=case.input_digest,
            status=AdapterStatus.COMPLETED,
        )


class TestAnalysisTrace(unittest.TestCase):
    def test_typed_projection_keeps_safe_facts_and_drops_private_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            trace = _trace(workspace)
            payload = trace.canonical_json()

            self.assertEqual(
                [event.sequence for event in trace.events],
                [1, 3, 4, 5],
            )
            self.assertEqual(trace.events[0].safe_data, {"path": "src/config.py"})
            self.assertNotIn("error_type", trace.events[3].safe_data)
            shell_call = trace.events[2]
            self.assertEqual(shell_call.safe_data["target"], "tests/test_config.py")
            self.assertNotIn("command", shell_call.safe_data)
            shell_result = trace.events[3]
            self.assertEqual(shell_result.safe_data["exit_code"], 0)
            self.assertEqual(shell_result.safe_data["test_count"], 4)

            private = project_analysis_trace(
                "task-1",
                "trace-private",
                (
                    ToolExecutionStartEvent(
                        tool_call_id="private-1",
                        tool_name="read_file",
                        args={
                            "file_path": str(workspace / "hidden" / "answer.py"),
                        },
                    ),
                    ToolExecutionStartEvent(
                        tool_call_id="outside-1",
                        tool_name="read_file",
                        args={"file_path": "../outside-secret.py"},
                    ),
                    ToolExecutionStartEvent(
                        tool_call_id="write-1",
                        tool_name="write_file",
                        args={
                            "file_path": "src/config.py",
                            "content": "private source body",
                            "authorization": "Bearer secret-value",
                        },
                    ),
                    ToolExecutionStartEvent(
                        tool_call_id="unknown-1",
                        tool_name="mystery_tool",
                        args={
                            "prompt": "hidden prompt",
                            "secret_token": "secret-value",
                            "safe_option": "value",
                        },
                    ),
                ),
                workspace=workspace,
            )
            private_payload = private.canonical_json()
            self.assertEqual(private.events[0].safe_data, {})
            self.assertEqual(private.events[1].safe_data, {})
            self.assertEqual(private.events[2].safe_data["operation"], "write")
            self.assertIn("content_digest", private.events[2].safe_data)
            self.assertEqual(private.events[3].action, "other")
            self.assertIn("safe_option", private.events[3].safe_data["argument_keys"])
            self.assertIn("sensitive", private.events[3].safe_data["argument_keys"])
            for raw in (
                "answer.py",
                "outside-secret.py",
                "private source body",
                "hidden prompt",
                "secret-value",
                "Bearer secret-value",
            ):
                self.assertNotIn(raw, private_payload)
            self.assertNotIn("stdout", payload)
            self.assertNotIn("stderr", payload)
            self.assertNotIn("source line must not persist", payload)

    def test_unknown_command_is_bounded_and_pytest_module_target_is_visible(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            unknown = project_analysis_trace(
                "task-1",
                "trace-unknown",
                (
                    ToolExecutionStartEvent(
                        tool_call_id="call-1",
                        tool_name="run_shell",
                        args={"command": "custom-run --password=secret-value"},
                    ),
                ),
                workspace=workspace,
            )
            self.assertEqual(unknown.events[0].safe_data["command_family"], "other")
            self.assertEqual(unknown.events[0].safe_data["argument_keys"], ["command"])
            self.assertNotIn("custom-run", unknown.canonical_json())
            self.assertNotIn("secret-value", unknown.canonical_json())

            pytest = project_analysis_trace(
                "task-1",
                "trace-pytest",
                (
                    ToolExecutionStartEvent(
                        tool_call_id="call-1",
                        tool_name="run_shell",
                        args={"command": "python -m pytest tests/test_config.py"},
                    ),
                ),
                workspace=workspace,
            )
            self.assertEqual(
                pytest.events[0].safe_data["target"], "tests/test_config.py"
            )

    def test_shell_syntax_and_control_text_degrade_without_raw_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            trace = project_analysis_trace(
                "task-1",
                "trace-unsafe-shell",
                (
                    ToolExecutionStartEvent(
                        tool_call_id="call-1",
                        tool_name="run_shell",
                        args={
                            "command": "python -c \"print('secret.py')\"; cat hidden.txt",
                        },
                    ),
                    ToolExecutionStartEvent(
                        tool_call_id="call-2",
                        tool_name="read_file",
                        args={"file_path": r"C:\workspace\secret.py"},
                    ),
                    ToolExecutionStartEvent(
                        tool_call_id="call-3",
                        tool_name="grep_search",
                        args={"pattern": "needle\nreasoning"},
                    ),
                ),
                workspace=workspace,
            )
            self.assertEqual(trace.events[0].safe_data["command_family"], "other")
            self.assertEqual(trace.events[1].safe_data, {})
            self.assertEqual(trace.events[2].safe_data, {})
            serialized = trace.canonical_json()
            self.assertNotIn("python -c", serialized)
            self.assertNotIn("secret.py", serialized)
            self.assertNotIn("reasoning", serialized)

    def test_round_trip_digest_schema_and_truncation_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            trace = _trace(workspace)
            path = workspace / "analysis-trace.json"
            trace.write_json(path)
            loaded = load_analysis_trace(
                path,
                expected_task_id="task-1",
                expected_trace_id="trace-1",
            )
            self.assertEqual(loaded, trace)
            self.assertEqual(loaded.canonical_json(), trace.canonical_json())

            invalid_digest = json.loads(trace.canonical_json())
            invalid_digest["trace_digest"] = "0" * 64
            with self.assertRaises(AnalysisTraceSchemaError):
                load_analysis_trace(invalid_digest)
            extra = json.loads(trace.canonical_json())
            extra["unexpected"] = True
            with self.assertRaises(AnalysisTraceSchemaError):
                load_analysis_trace(extra)
            with self.assertRaises(AnalysisTraceUnavailable):
                load_analysis_trace(workspace / "missing.json")

            truncated = project_analysis_trace(
                "task-1",
                "trace-truncated",
                tuple(
                    ToolExecutionStartEvent(
                        tool_call_id=f"call-{index}",
                        tool_name="read_file",
                        args={"file_path": f"src/file-{index}.py"},
                    )
                    for index in range(3)
                ),
                workspace=workspace,
                max_events=2,
            )
            self.assertTrue(truncated.truncated)
            self.assertEqual(truncated.event_count, 2)
            self.assertEqual([event.sequence for event in truncated.events], [1, 2])

    def test_reasonable_and_degraded_same_context_have_directional_difference(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            reasonable = DeepEvalAnalysisCase(
                task_id="task-1",
                input_digest=_digest("same public task"),
                analysis_trace=_trace(workspace),
            )
            degraded = DeepEvalAnalysisCase(
                task_id="task-1",
                input_digest=reasonable.input_digest,
                analysis_trace=_trace(workspace, degraded=True),
            )
            good = analyze_deepeval_case(
                reasonable,
                judge_model="fake-judge",
                judge=_DirectionalJudge(),
                timeout_seconds=None,
                judge_samples=1,
            )
            bad = analyze_deepeval_case(
                degraded,
                judge_model="fake-judge",
                judge=_DirectionalJudge(),
                timeout_seconds=None,
                judge_samples=1,
            )
            self.assertEqual(good.input_digest, bad.input_digest)
            self.assertGreater(good.metrics[0].score, bad.metrics[0].score)
            self.assertGreater(good.metrics[1].score, bad.metrics[1].score)

    def test_judge_sequence_reference_is_preserved_or_explicitly_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace = _trace(Path(directory))
            case = DeepEvalAnalysisCase(
                task_id="task-1",
                input_digest=_digest("same public task"),
                analysis_trace=trace,
            )

            supplied = analyze_deepeval_case(
                case,
                judge_model="fake-judge",
                judge=_ReasonJudge("judge linked [seq=5]"),
                timeout_seconds=None,
                judge_samples=1,
            )
            self.assertEqual(
                [metric.reason for metric in supplied.metrics],
                ["judge linked [seq=5]"] * 2,
            )

            missing = analyze_deepeval_case(
                case,
                judge_model="fake-judge",
                judge=_ReasonJudge("judge omitted location"),
                timeout_seconds=None,
                judge_samples=1,
            )
            for metric in missing.metrics:
                self.assertIn("（Judge 未提供 sequence 定位）", metric.reason or "")
                self.assertNotIn("[seq=", metric.reason or "")
                self.assertLessEqual(len(metric.reason or ""), 320)

            empty = analyze_deepeval_case(
                case,
                judge_model="fake-judge",
                judge=_ReasonJudge(None),
                timeout_seconds=None,
                judge_samples=1,
            )
            self.assertTrue(
                all(
                    metric.reason
                    == "DeepEval metric completed （Judge 未提供 sequence 定位）"
                    for metric in empty.metrics
                )
            )

            empty_trace_case = DeepEvalAnalysisCase(
                task_id="task-1",
                input_digest=case.input_digest,
                analysis_trace=AnalysisTrace.from_events(
                    task_id="task-1",
                    trace_id="trace-empty",
                    events=(),
                ),
            )
            empty_trace = analyze_deepeval_case(
                empty_trace_case,
                judge_model="fake-judge",
                judge=_ReasonJudge("judge omitted location"),
                timeout_seconds=None,
                judge_samples=1,
            )
            self.assertTrue(
                all(
                    "（Judge 未提供 sequence 定位）" in (metric.reason or "")
                    for metric in empty_trace.metrics
                )
            )

    def test_judge_invalid_sequence_reference_is_marked_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            trace = _trace(Path(directory))
            case = DeepEvalAnalysisCase(
                task_id="task-1",
                input_digest=_digest("same public task"),
                analysis_trace=trace,
            )

            invalid = analyze_deepeval_case(
                case,
                judge_model="fake-judge",
                judge=_ReasonJudge("judge linked [seq=999]"),
                timeout_seconds=None,
                judge_samples=1,
            )
            self.assertEqual(
                [metric.reason for metric in invalid.metrics],
                ["Judge sequence 定位无效"] * 2,
            )

            malformed = analyze_deepeval_case(
                case,
                judge_model="fake-judge",
                judge=_ReasonJudge("judge linked [seq=abc]"),
                timeout_seconds=None,
                judge_samples=1,
            )
            self.assertEqual(
                [metric.reason for metric in malformed.metrics],
                ["Judge sequence 定位无效"] * 2,
            )

    def test_sdk_judge_passes_safe_parameters_and_ordered_trace_to_both_metrics(
        self,
    ) -> None:
        created_metrics: list[object] = []

        class FakeMetric:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs
                self.score = None
                self.reason = None
                self.last_case = None
                created_metrics.append(self)

            def measure(self, test_case: object) -> None:
                self.last_case = test_case
                self.score = 0.8
                self.reason = "metric reason [seq=1]"

        class FakeArgumentCorrectnessMetric(FakeMetric):
            pass

        class FakeGEval(FakeMetric):
            pass

        class FakeToolCall:
            def __init__(self, *, name: str, input_parameters: dict) -> None:
                self.name = name
                self.input_parameters = input_parameters

        class FakeLLMTestCase:
            def __init__(self, **kwargs: object) -> None:
                self.__dict__.update(kwargs)

        metrics_module = ModuleType("deepeval.metrics")
        metrics_module.ArgumentCorrectnessMetric = FakeArgumentCorrectnessMetric
        metrics_module.GEval = FakeGEval
        test_case_module = ModuleType("deepeval.test_case")
        test_case_module.SingleTurnParams = SimpleNamespace(
            INPUT="input",
            ACTUAL_OUTPUT="actual_output",
        )
        test_case_module.ToolCall = FakeToolCall
        test_case_module.LLMTestCase = FakeLLMTestCase
        deepeval_module = ModuleType("deepeval")

        with tempfile.TemporaryDirectory() as directory:
            trace = _trace(Path(directory))
            case = DeepEvalAnalysisCase(
                task_id="task-1",
                input_digest=_digest("input"),
                analysis_trace=trace,
            )
            with patch.dict(
                sys.modules,
                {
                    "deepeval": deepeval_module,
                    "deepeval.metrics": metrics_module,
                    "deepeval.test_case": test_case_module,
                },
            ):
                judge = DeepEvalSdkJudge(judge_model="fake-judge")
                observations = [
                    judge.evaluate_metric(metric_name=name, case=case)
                    for name in ("ArgumentCorrectnessMetric", "ToolDecisionQuality")
                ]

            self.assertEqual(
                [observation.score for observation in observations], [0.8, 0.8]
            )
            self.assertEqual(len(created_metrics), 2)
            argument_case = created_metrics[0].last_case
            decision_case = created_metrics[1].last_case
            self.assertEqual(argument_case.tools_called[0].name, "read_file")
            self.assertEqual(
                argument_case.tools_called[0].input_parameters,
                {"path": "src/config.py"},
            )
            self.assertIn("[seq=1]", decision_case.actual_output)
            self.assertIn("[seq=5]", decision_case.actual_output)
            self.assertNotIn("python -m pytest", decision_case.actual_output)


if __name__ == "__main__":
    unittest.main()
