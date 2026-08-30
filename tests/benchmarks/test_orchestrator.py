"""单题离线运行器的生命周期、cleanup 与 checkpoint 测试。"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from benchmarks.agent_e2e.backend import (
    FakeContainerBackend,
    IsolationReport,
    UnavailableContainerBackend,
)
from benchmarks.agent_e2e.catalog import freeze_catalog
from benchmarks.agent_e2e.checkpoint import InMemoryCheckpointStore
from benchmarks.agent_e2e.fixtures import (
    AGENT_CODE_SHA,
    EVALUATOR_CODE_SHA,
)
from benchmarks.agent_e2e.fixtures import (
    make_task as make_verified_task,
)
from benchmarks.agent_e2e.models import (
    AgentRunSummary,
    Catalog,
    ExperimentManifest,
    ExperimentProfile,
    ResultValidity,
    TaskSpec,
    TaskVerdict,
    WorkerResult,
    WorkerStatus,
)
from benchmarks.agent_e2e.orchestrator import SingleTaskOrchestrator
from benchmarks.agent_e2e.report import build_report, render_chinese_markdown


def make_task() -> TaskSpec:
    return make_verified_task(task_id="task-1", verifier_identity="hidden-v1")


def make_manifest(task: TaskSpec) -> ExperimentManifest:
    catalog = Catalog(catalog_id="local", catalog_version="v1", tasks=(task,))
    profile = ExperimentProfile(
        profile_id="offline-test",
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
        run_id="offline-run",
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


def completed_worker() -> WorkerResult:
    return WorkerResult(
        status=WorkerStatus.COMPLETED,
        agent_run=AgentRunSummary(
            final_text_digest=hashlib.sha256(b"done").hexdigest(),
            final_text_preview="done",
            stop_reason="completed",
            turns=1,
            wall_time_seconds=1,
            input_tokens=2,
            output_tokens=3,
            cache_read_tokens=0,
            cost_usd=0,
        ),
        patch_sha256=hashlib.sha256(b"patch").hexdigest(),
        patch_applied=True,
    )


class TestSingleTaskOrchestrator(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.task = make_task()
        self.manifest = make_manifest(self.task)

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    def _orchestrator(self, backend, checkpoints=None) -> SingleTaskOrchestrator:
        return SingleTaskOrchestrator(
            backend=backend,
            checkpoint_store=checkpoints,
            work_root=self.temp_dir.name,
        )

    async def test_fake_success_runs_worker_verifier_cleanup_but_stays_offline(
        self,
    ) -> None:
        backend = FakeContainerBackend(
            worker_handler=lambda _request: _return(completed_worker())
        )
        result = await self._orchestrator(backend).run_task(
            manifest=self.manifest,
            task=self.task,
        )

        self.assertEqual(result.verdict, TaskVerdict.BLOCKED)
        self.assertEqual(result.validity, ResultValidity.OFFLINE_ONLY)
        self.assertFalse(result.official)
        self.assertIsNotNone(result.verifier)
        self.assertEqual(len(backend.agent_requests), 1)
        self.assertEqual(len(backend.verifier_requests), 1)
        self.assertEqual(len(backend.cleanup_calls), 1)
        report = build_report(manifest=self.manifest, results=[result])
        self.assertIsNone(report.official_score)
        self.assertNotIn("task_resolved", report.canonical_json())
        self.assertNotIn("task_resolved", render_chinese_markdown(report))

    async def test_unavailable_backend_is_blocked_without_worker_or_verifier(
        self,
    ) -> None:
        backend = UnavailableContainerBackend("Docker daemon is unavailable")
        result = await self._orchestrator(backend).run_task(
            manifest=self.manifest,
            task=self.task,
        )

        self.assertEqual(result.verdict, TaskVerdict.BLOCKED)
        self.assertEqual(result.validity, ResultValidity.BLOCKED)
        self.assertIn("Docker daemon", result.invalid_reason or "")
        self.assertEqual(len(backend.cleanup_calls), 1)
        self.assertNotIn("task_resolved", result.canonical_json())

    async def test_timeout_worker_exception_verifier_exception_and_cleanup_failure_are_invalid(
        self,
    ) -> None:
        timeout_backend = FakeContainerBackend(
            worker_handler=lambda _request: _return(
                WorkerResult(status=WorkerStatus.TIMEOUT, error_summary="timed out")
            )
        )
        timeout_result = await self._orchestrator(timeout_backend).run_task(
            manifest=self.manifest,
            task=self.task,
        )
        self.assertEqual(timeout_result.verdict, TaskVerdict.INVALID)
        self.assertEqual(len(timeout_backend.verifier_requests), 0)
        self.assertEqual(len(timeout_backend.cleanup_calls), 1)

        async def worker_failure(_request):
            raise RuntimeError("worker exploded")

        worker_backend = FakeContainerBackend(worker_handler=worker_failure)
        worker_result = await self._orchestrator(worker_backend).run_task(
            manifest=self.manifest,
            task=self.task,
            attempt=2,
        )
        self.assertEqual(worker_result.verdict, TaskVerdict.INVALID)
        self.assertIn("orchestrator error", worker_result.invalid_reason or "")
        self.assertEqual(len(worker_backend.cleanup_calls), 1)

        async def verifier_failure(_request):
            raise RuntimeError("verifier exploded")

        verifier_backend = FakeContainerBackend(
            worker_handler=lambda _request: _return(completed_worker()),
            verifier_handler=verifier_failure,
        )
        verifier_result = await self._orchestrator(verifier_backend).run_task(
            manifest=self.manifest,
            task=self.task,
            attempt=3,
        )
        self.assertEqual(verifier_result.verdict, TaskVerdict.INVALID)
        self.assertIn("verifier error", verifier_result.invalid_reason or "")
        self.assertEqual(len(verifier_backend.cleanup_calls), 1)

        cleanup_backend = FakeContainerBackend(
            worker_handler=lambda _request: _return(completed_worker()),
            cleanup_error=RuntimeError("cleanup exploded"),
        )
        cleanup_result = await self._orchestrator(cleanup_backend).run_task(
            manifest=self.manifest,
            task=self.task,
            attempt=4,
        )
        self.assertEqual(cleanup_result.verdict, TaskVerdict.INVALID)
        self.assertIn("cleanup failed", cleanup_result.invalid_reason or "")

    async def test_checkpoint_restores_without_rerunning_backend(self) -> None:
        checkpoints = InMemoryCheckpointStore()
        backend = FakeContainerBackend(
            worker_handler=lambda _request: _return(completed_worker())
        )
        orchestrator = self._orchestrator(backend, checkpoints)

        first = await orchestrator.run_task(manifest=self.manifest, task=self.task)
        restored = await orchestrator.run_task(manifest=self.manifest, task=self.task)

        self.assertFalse(first.resumed_from_checkpoint)
        self.assertTrue(restored.resumed_from_checkpoint)
        self.assertEqual(len(backend.agent_requests), 1)
        self.assertEqual(len(backend.cleanup_calls), 1)

    async def test_unsafe_workspace_contract_stops_before_worker(self) -> None:
        backend = FakeContainerBackend(shared_workspace=True)
        result = await self._orchestrator(backend).run_task(
            manifest=self.manifest,
            task=self.task,
        )

        self.assertEqual(result.verdict, TaskVerdict.INVALID)
        self.assertEqual(len(backend.agent_requests), 0)
        self.assertEqual(len(backend.cleanup_calls), 1)

    def test_nested_workspaces_are_not_an_isolation_boundary(self) -> None:
        verifier_workspace = tempfile.TemporaryDirectory()
        self.addCleanup(verifier_workspace.cleanup)
        verifier_path = Path(verifier_workspace.name)
        nested_agent = verifier_path / "agent-workspace"

        report = IsolationReport(
            agent_workspace=nested_agent,
            verifier_workspace=verifier_path,
            private_assets_visible_to_agent=False,
        )

        self.assertFalse(report.workspaces_are_separate)
        self.assertFalse(report.official_safe)


async def _return(value):
    return value


if __name__ == "__main__":
    unittest.main()
