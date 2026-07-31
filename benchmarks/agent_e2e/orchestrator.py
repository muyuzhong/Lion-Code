"""单题评测生命周期：校验、隔离、worker、verifier、checkpoint 与清理。"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from .backend import (
    AgentExecutionRequest,
    BackendUnavailableError,
    ContainerBackend,
    VerifierExecutionRequest,
)
from .checkpoint import CheckpointStore, InMemoryCheckpointStore
from .models import (
    ExperimentManifest,
    ResultValidity,
    TaskResult,
    TaskSpec,
    TaskVerdict,
    VerifierOutcome,
    WorkerResult,
    WorkerStatus,
    utc_now,
)
from .trace import redact_text


class ManifestValidationError(ValueError):
    """manifest 与本次单题输入不一致，不能进入执行器。"""


class SingleTaskOrchestrator:
    """只运行一个 task/attempt 的 host 编排器。

    Fake 和 unavailable backend 都可以覆盖完整生命周期，但由于不具备真实隔离
    背书，结果只能是 blocked 或 invalid，绝不生成正式 passed/failed。
    """

    def __init__(
        self,
        *,
        backend: ContainerBackend,
        checkpoint_store: CheckpointStore | None = None,
        work_root: str | Path | None = None,
    ) -> None:
        self.backend = backend
        self.checkpoint_store = checkpoint_store or InMemoryCheckpointStore()
        self.work_root = Path(work_root) if work_root is not None else None

    async def run_task(
        self,
        *,
        manifest: ExperimentManifest,
        task: TaskSpec,
        attempt: int = 1,
        resume: bool = True,
    ) -> TaskResult:
        """执行或恢复一题；任何非隔离路径都不能返回正式成绩。"""

        _validate_manifest_task(manifest, task, attempt)
        if resume:
            checkpoint = await self.checkpoint_store.load(
                run_id=manifest.run_id,
                task_id=task.task_id,
                attempt=attempt,
            )
            if checkpoint is not None:
                return checkpoint.model_copy(update={"resumed_from_checkpoint": True})

        started_at = utc_now()
        agent_workspace, verifier_workspace, session_root = self._workspace_paths(
            manifest=manifest,
            task=task,
            attempt=attempt,
        )
        agent_request = AgentExecutionRequest(
            manifest=manifest,
            task=task,
            attempt=attempt,
            agent_workspace=agent_workspace,
            session_root=session_root,
            mcp_enabled=False,
        )
        result: TaskResult | None = None
        try:
            if not self.backend.available:
                result = _blocked_result(
                    task=task,
                    attempt=attempt,
                    reason=self.backend.unavailable_reason or "Container backend unavailable",
                    started_at=started_at,
                    validity=ResultValidity.BLOCKED,
                )
            else:
                isolation = await self.backend.inspect_isolation(
                    agent_request,
                    verifier_workspace=verifier_workspace,
                )
                if not isolation.official_safe:
                    result = _invalid_result(
                        task=task,
                        attempt=attempt,
                        reason="Isolation contract failed: agent/verifier workspaces or private assets are unsafe",
                        started_at=started_at,
                    )
                else:
                    worker = await self.backend.run_agent(agent_request)
                    result = await self._result_after_worker(
                        manifest=manifest,
                        task=task,
                        attempt=attempt,
                        worker=worker,
                        verifier_workspace=verifier_workspace,
                        started_at=started_at,
                    )
        except asyncio.CancelledError:
            raise
        except BackendUnavailableError as error:
            result = _blocked_result(
                task=task,
                attempt=attempt,
                reason=str(error),
                started_at=started_at,
                validity=ResultValidity.BLOCKED,
            )
        except Exception as error:
            reason, _ = redact_text(str(error) or error.__class__.__name__)
            result = _invalid_result(
                task=task,
                attempt=attempt,
                reason=f"orchestrator error: {reason}",
                started_at=started_at,
            )
        finally:
            try:
                await self.backend.cleanup(
                    run_id=manifest.run_id,
                    task_id=task.task_id,
                    attempt=attempt,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                reason, _ = redact_text(str(error) or error.__class__.__name__)
                result = _invalid_result(
                    task=task,
                    attempt=attempt,
                    reason=f"cleanup failed: {reason}",
                    started_at=started_at,
                    prior=result,
                )
            if result is not None:
                await self.checkpoint_store.save(result, run_id=manifest.run_id)
        assert result is not None
        return result

    async def _result_after_worker(
        self,
        *,
        manifest: ExperimentManifest,
        task: TaskSpec,
        attempt: int,
        worker: WorkerResult,
        verifier_workspace: Path,
        started_at: datetime,
    ) -> TaskResult:
        if worker.status is WorkerStatus.TIMEOUT:
            return _invalid_result(
                task=task,
                attempt=attempt,
                reason=f"worker timeout: {worker.error_summary}",
                started_at=started_at,
                worker=worker,
            )
        if worker.status is WorkerStatus.ERROR:
            return _invalid_result(
                task=task,
                attempt=attempt,
                reason=f"worker error: {worker.error_summary}",
                started_at=started_at,
                worker=worker,
            )
        verifier_request = VerifierExecutionRequest(
            manifest=manifest,
            task=task,
            attempt=attempt,
            verifier_workspace=verifier_workspace,
            patch_sha256=worker.patch_sha256,
        )
        try:
            verifier = await self.backend.run_verifier(verifier_request)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            reason, _ = redact_text(str(error) or error.__class__.__name__)
            return _invalid_result(
                task=task,
                attempt=attempt,
                reason=f"verifier error: {reason}",
                started_at=started_at,
                worker=worker,
            )

        if not self.backend.supports_official_scores:
            return _blocked_result(
                task=task,
                attempt=attempt,
                reason="Offline/fake container backend cannot produce official scores",
                started_at=started_at,
                validity=ResultValidity.OFFLINE_ONLY,
                worker=worker,
                verifier=verifier,
            )
        verdict = (
            TaskVerdict.PASSED
            if verifier.outcome is VerifierOutcome.PASSED
            else TaskVerdict.FAILED
        )
        return TaskResult(
            task_id=task.task_id,
            attempt=attempt,
            verdict=verdict,
            validity=ResultValidity.VALID,
            official=True,
            patch_sha256=worker.patch_sha256,
            patch_applied=worker.patch_applied,
            agent_run=worker.agent_run,
            trace_summary=worker.trace_summary,
            verifier=verifier,
            cost_usd=worker.agent_run.cost_usd if worker.agent_run is not None else 0,
            started_at=started_at,
            finished_at=utc_now(),
        )

    def _workspace_paths(
        self,
        *,
        manifest: ExperimentManifest,
        task: TaskSpec,
        attempt: int,
    ) -> tuple[Path, Path, Path]:
        if self.work_root is None:
            root = Path.cwd() / ".agent-e2e-work"
        else:
            root = self.work_root
        task_root = root / manifest.run_id / task.task_id / f"attempt-{attempt}"
        agent_workspace = task_root / "agent-workspace"
        verifier_workspace = task_root / "verifier-workspace"
        session_root = task_root / "sessions"
        # 只建立空目录，真实 worktree/镜像由将来的 Docker backend 负责填充。
        agent_workspace.mkdir(parents=True, exist_ok=True)
        verifier_workspace.mkdir(parents=True, exist_ok=True)
        session_root.mkdir(parents=True, exist_ok=True)
        return agent_workspace, verifier_workspace, session_root


OfflineOrchestrator = SingleTaskOrchestrator


def _validate_manifest_task(
    manifest: ExperimentManifest,
    task: TaskSpec,
    attempt: int,
) -> None:
    if attempt < 1:
        raise ManifestValidationError("attempt must be positive")
    if task.task_id not in manifest.task_ids:
        raise ManifestValidationError("task is not selected by manifest")
    if task.task_id not in manifest.catalog.task_ids:
        raise ManifestValidationError("task is not present in manifest catalog lock")


def _blocked_result(
    *,
    task: TaskSpec,
    attempt: int,
    reason: str,
    started_at: datetime,
    validity: ResultValidity,
    worker: WorkerResult | None = None,
    verifier=None,
) -> TaskResult:
    return TaskResult(
        task_id=task.task_id,
        attempt=attempt,
        verdict=TaskVerdict.BLOCKED,
        validity=validity,
        official=False,
        patch_sha256=worker.patch_sha256 if worker is not None else None,
        patch_applied=worker.patch_applied if worker is not None else None,
        agent_run=worker.agent_run if worker is not None else None,
        trace_summary=worker.trace_summary if worker is not None else None,
        verifier=verifier,
        cost_usd=(worker.agent_run.cost_usd if worker and worker.agent_run else 0),
        started_at=started_at,
        finished_at=utc_now(),
        invalid_reason=reason,
    )


def _invalid_result(
    *,
    task: TaskSpec,
    attempt: int,
    reason: str,
    started_at: datetime,
    worker: WorkerResult | None = None,
    prior: TaskResult | None = None,
) -> TaskResult:
    return TaskResult(
        task_id=task.task_id,
        attempt=attempt,
        verdict=TaskVerdict.INVALID,
        validity=ResultValidity.INVALID,
        official=False,
        patch_sha256=(
            worker.patch_sha256
            if worker is not None
            else prior.patch_sha256 if prior is not None else None
        ),
        patch_applied=(
            worker.patch_applied
            if worker is not None
            else prior.patch_applied if prior is not None else None
        ),
        agent_run=(
            worker.agent_run
            if worker is not None
            else prior.agent_run if prior is not None else None
        ),
        trace_summary=(
            worker.trace_summary
            if worker is not None
            else prior.trace_summary if prior is not None else None
        ),
        verifier=prior.verifier if prior is not None else None,
        cost_usd=(
            worker.agent_run.cost_usd
            if worker is not None and worker.agent_run is not None
            else prior.cost_usd if prior is not None else 0
        ),
        started_at=started_at,
        finished_at=utc_now(),
        invalid_reason=reason,
    )
