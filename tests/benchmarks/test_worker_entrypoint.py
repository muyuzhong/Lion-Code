"""worker 入口的 Analysis Trace 旁路隔离回归测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from benchmarks.agent_e2e import worker_entrypoint
from benchmarks.agent_e2e.catalog import freeze_catalog
from benchmarks.agent_e2e.fixtures import AGENT_CODE_SHA, EVALUATOR_CODE_SHA, make_task
from benchmarks.agent_e2e.models import (
    AgentRunSummary,
    Catalog,
    ExperimentManifest,
    ExperimentProfile,
    TaskSpec,
    TraceSummary,
    WorkerResult,
    WorkerStatus,
)
from benchmarks.agent_e2e.trace import TraceRecorder


def _task() -> TaskSpec:
    return make_task(
        task_id="entrypoint-task",
        public_validation_commands=("python -m pytest -q",),
    )


def _manifest(task: TaskSpec) -> ExperimentManifest:
    catalog = Catalog(catalog_id="entrypoint", catalog_version="v1", tasks=(task,))
    profile = ExperimentProfile(
        profile_id="entrypoint-profile",
        model="fake-model",
        provider="fake",
        prompt_version="prompt-v1",
        compression_version="compression-v1",
        tool_policy_version="tools-v1",
        seed=7,
        repeats=1,
        timeout_seconds=30,
        budget_usd=0,
        agent_code_sha=AGENT_CODE_SHA,
    )
    return ExperimentManifest(
        run_id="entrypoint-run",
        agent_code_sha=profile.agent_code_sha,
        evaluator_code_sha=EVALUATOR_CODE_SHA,
        catalog=freeze_catalog(catalog),
        profile=profile,
        profile_fingerprint=profile.fingerprint(),
        task_ids=(task.task_id,),
        seed=profile.seed,
        repeats=profile.repeats,
        timeout_seconds=profile.timeout_seconds,
        budget_usd=profile.budget_usd,
        platform="offline-test",
    )


def _completed_result() -> WorkerResult:
    return WorkerResult(
        status=WorkerStatus.COMPLETED,
        agent_run=AgentRunSummary(
            final_text_digest="a" * 64,
            final_text_preview="完成",
            stop_reason="completed",
            turns=1,
            wall_time_seconds=0.1,
            input_tokens=1,
            output_tokens=1,
            cache_read_tokens=0,
            cost_usd=0,
        ),
        trace_summary=TraceSummary(
            trace_id="entrypoint-trace",
            event_count=0,
            redaction_count=0,
            trace_digest="b" * 64,
        ),
    )


class TestWorkerEntrypoint(unittest.TestCase):
    def _patch_entrypoint_paths(self, root: Path):
        request_path = root / "request.json"
        log_root = root / "logs"
        return (
            patch.object(worker_entrypoint, "REQUEST_PATH", request_path),
            patch.object(worker_entrypoint, "LOG_ROOT", log_root),
            patch.object(worker_entrypoint, "PATCH_PATH", log_root / "lion.patch"),
            patch.object(
                worker_entrypoint,
                "RESULT_PATH",
                log_root / "worker-result.json",
            ),
            patch.object(worker_entrypoint, "TRACE_PATH", log_root / "trace.json"),
            patch.object(
                worker_entrypoint,
                "ANALYSIS_TRACE_PATH",
                log_root / "analysis-trace.json",
            ),
        )

    def _run_with_analysis_failure(
        self,
        root: Path,
        failure_patch,
    ) -> tuple[Path, Path, Path, Path]:
        task = _task()
        manifest = _manifest(task)
        request_path = root / "request.json"
        request_path.write_text(
            json.dumps(
                {
                    "manifest": manifest.model_dump(mode="json"),
                    "task": task.model_dump(mode="json"),
                    "attempt": 1,
                }
            ),
            encoding="utf-8",
        )
        log_root = root / "logs"
        paths = self._patch_entrypoint_paths(root)

        def write_patch(_workspace, destination, *, base_revision=None):
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"patch")
            return "c" * 64, True

        worker = AsyncMock(return_value=_completed_result())
        with (
            paths[0],
            paths[1],
            paths[2],
            paths[3],
            paths[4],
            paths[5],
            patch.object(worker_entrypoint, "run_agent_worker", worker),
            patch.object(
                worker_entrypoint, "export_git_patch", side_effect=write_patch
            ),
            failure_patch,
        ):
            result = worker_entrypoint.main()

        self.assertEqual(result, 0)
        return (
            log_root / "worker-result.json",
            log_root / "trace.json",
            log_root / "lion.patch",
            log_root / "analysis-trace.json",
        )

    def test_analysis_trace_build_failure_keeps_formal_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            analysis_path = root / "logs" / "analysis-trace.json"
            analysis_path.parent.mkdir(parents=True)
            analysis_path.write_text("stale", encoding="utf-8")
            failure = patch.object(
                TraceRecorder,
                "build_analysis_trace",
                side_effect=RuntimeError("analysis build failed"),
            )
            result_path, trace_path, patch_path, analysis_path = (
                self._run_with_analysis_failure(root, failure)
            )

            self.assertTrue(result_path.is_file())
            self.assertTrue(trace_path.is_file())
            self.assertTrue(patch_path.is_file())
            self.assertFalse(analysis_path.exists())
            result = WorkerResult.from_dict(json.loads(result_path.read_text()))
            self.assertEqual(result.status, WorkerStatus.COMPLETED)
            self.assertEqual(result.patch_sha256, "c" * 64)
            self.assertTrue(result.patch_applied)

    def test_analysis_trace_write_failure_cleans_partial_file(self) -> None:
        def write_partial(_recorder, path, *, task_id):
            Path(path).write_text("partial", encoding="utf-8")
            raise OSError("analysis write failed")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failure = patch.object(
                TraceRecorder,
                "write_analysis_trace",
                autospec=True,
                side_effect=write_partial,
            )
            result_path, trace_path, patch_path, analysis_path = (
                self._run_with_analysis_failure(root, failure)
            )

            self.assertTrue(result_path.is_file())
            self.assertTrue(trace_path.is_file())
            self.assertTrue(patch_path.is_file())
            self.assertFalse(analysis_path.exists())


if __name__ == "__main__":
    unittest.main()
