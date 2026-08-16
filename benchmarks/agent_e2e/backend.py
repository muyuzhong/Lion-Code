"""容器执行边界；foundation 只提供不可执行的真实路径和安全 fake。"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from .models import (
    AgentRunSummary,
    ExperimentManifest,
    TaskSpec,
    VerifierOutcome,
    VerifierResult,
    WorkerResult,
    WorkerStatus,
)


class BackendUnavailableError(RuntimeError):
    """没有可用隔离执行器时的可解释阻塞原因。"""


@dataclass(frozen=True, slots=True)
class AgentExecutionRequest:
    """只包含 Agent 容器可见信息的执行请求。"""

    manifest: ExperimentManifest
    task: TaskSpec
    attempt: int
    agent_workspace: Path
    session_root: Path


@dataclass(frozen=True, slots=True)
class VerifierExecutionRequest:
    """Host 到 verifier 的私有验收请求；不反向暴露给 Agent。"""

    manifest: ExperimentManifest
    task: TaskSpec
    attempt: int
    verifier_workspace: Path
    patch_sha256: str | None


@dataclass(frozen=True, slots=True)
class IsolationReport:
    """host 对容器挂载关系的最小可验证断言。"""

    agent_workspace: Path
    verifier_workspace: Path
    private_assets_visible_to_agent: bool

    @property
    def workspaces_are_separate(self) -> bool:
        """只有两个工作区互不包含时，Agent 才无法直接读取 verifier 内容。"""

        agent_workspace = self.agent_workspace.resolve()
        verifier_workspace = self.verifier_workspace.resolve()
        return not _paths_overlap(agent_workspace, verifier_workspace)

    @property
    def official_safe(self) -> bool:
        return self.workspaces_are_separate and not self.private_assets_visible_to_agent


def _paths_overlap(first: Path, second: Path) -> bool:
    """判断路径相同或任一方位于另一方内部，避免只比较相等路径漏掉嵌套挂载。"""

    try:
        first.relative_to(second)
        return True
    except ValueError:
        pass
    try:
        second.relative_to(first)
        return True
    except ValueError:
        return False


@runtime_checkable
class ContainerBackend(Protocol):
    """正式容器 backend 的协议；当前 foundation 不实现真实 Docker 调度。"""

    @property
    def available(self) -> bool:
        """是否可启动隔离的 Agent 和 verifier 容器。"""
        ...

    @property
    def supports_official_scores(self) -> bool:
        """是否由真实隔离实现背书，可写 passed/failed。"""
        ...

    @property
    def unavailable_reason(self) -> str | None:
        """不可用时返回人可读原因。"""
        ...

    async def inspect_isolation(
        self,
        request: AgentExecutionRequest,
        *,
        verifier_workspace: Path,
    ) -> IsolationReport:
        """返回本次挂载/工作区隔离事实。"""
        ...

    async def run_agent(self, request: AgentExecutionRequest) -> WorkerResult:
        """运行 Agent 容器，并返回受控 worker 结果。"""
        ...

    async def run_verifier(
        self,
        request: VerifierExecutionRequest,
    ) -> VerifierResult:
        """运行后置 verifier；Agent 已无法观察其输出。"""
        ...

    async def cleanup(self, *, run_id: str, task_id: str, attempt: int) -> None:
        """清理本次容器和临时卷；调用方在所有终止路径调用一次。"""
        ...


class UnavailableContainerBackend:
    """Docker/在线执行不可用时的显式 backend，永不启动子进程。"""

    def __init__(self, reason: str = "Docker daemon is unavailable") -> None:
        self._reason = reason
        self.cleanup_calls: list[tuple[str, str, int]] = []

    @property
    def available(self) -> bool:
        return False

    @property
    def supports_official_scores(self) -> bool:
        return False

    @property
    def unavailable_reason(self) -> str:
        return self._reason

    async def inspect_isolation(
        self,
        request: AgentExecutionRequest,
        *,
        verifier_workspace: Path,
    ) -> IsolationReport:
        raise BackendUnavailableError(self._reason)

    async def run_agent(self, request: AgentExecutionRequest) -> WorkerResult:
        raise BackendUnavailableError(self._reason)

    async def run_verifier(
        self,
        request: VerifierExecutionRequest,
    ) -> VerifierResult:
        raise BackendUnavailableError(self._reason)

    async def cleanup(self, *, run_id: str, task_id: str, attempt: int) -> None:
        self.cleanup_calls.append((run_id, task_id, attempt))


WorkerHandler = Callable[[AgentExecutionRequest], Awaitable[WorkerResult]]
VerifierHandler = Callable[[VerifierExecutionRequest], Awaitable[VerifierResult]]


class FakeContainerBackend:
    """仅用于离线测试的确定性 backend，永远不能生产正式成绩。"""

    def __init__(
        self,
        *,
        worker_handler: WorkerHandler | None = None,
        verifier_handler: VerifierHandler | None = None,
        private_assets_visible_to_agent: bool = False,
        shared_workspace: bool = False,
        cleanup_error: Exception | None = None,
    ) -> None:
        self.worker_handler = worker_handler
        self.verifier_handler = verifier_handler
        self.private_assets_visible_to_agent = private_assets_visible_to_agent
        self.shared_workspace = shared_workspace
        self.cleanup_error = cleanup_error
        self.agent_requests: list[AgentExecutionRequest] = []
        self.verifier_requests: list[VerifierExecutionRequest] = []
        self.cleanup_calls: list[tuple[str, str, int]] = []

    @property
    def available(self) -> bool:
        return True

    @property
    def supports_official_scores(self) -> bool:
        # Fake 返回的 verifier outcome 只用于生命周期测试，绝不构成正式得分。
        return False

    @property
    def unavailable_reason(self) -> None:
        return None

    async def inspect_isolation(
        self,
        request: AgentExecutionRequest,
        *,
        verifier_workspace: Path,
    ) -> IsolationReport:
        agent_workspace = (
            verifier_workspace if self.shared_workspace else request.agent_workspace
        )
        return IsolationReport(
            agent_workspace=agent_workspace,
            verifier_workspace=verifier_workspace,
            private_assets_visible_to_agent=self.private_assets_visible_to_agent,
        )

    async def run_agent(self, request: AgentExecutionRequest) -> WorkerResult:
        self.agent_requests.append(request)
        if self.worker_handler is not None:
            return await self.worker_handler(request)
        return _default_worker_result()

    async def run_verifier(
        self,
        request: VerifierExecutionRequest,
    ) -> VerifierResult:
        self.verifier_requests.append(request)
        if self.verifier_handler is not None:
            return await self.verifier_handler(request)
        return _default_verifier_result()

    async def cleanup(self, *, run_id: str, task_id: str, attempt: int) -> None:
        self.cleanup_calls.append((run_id, task_id, attempt))
        if self.cleanup_error is not None:
            raise self.cleanup_error


# 文档和测试可用的名称；它不接触 Docker daemon。
FakeDockerBackend = FakeContainerBackend


def unavailable_backend_for_host() -> UnavailableContainerBackend:
    """返回当前 foundation 的默认 backend，刻意不探测或调用 Docker CLI。"""

    return UnavailableContainerBackend(
        "Real Docker execution is not enabled by the evaluation foundation"
    )


def _default_worker_result() -> WorkerResult:
    digest = hashlib.sha256(b"").hexdigest()
    return WorkerResult(
        status=WorkerStatus.COMPLETED,
        agent_run=AgentRunSummary(
            final_text_digest=digest,
            stop_reason="completed",
            turns=0,
            wall_time_seconds=0,
            input_tokens=0,
            output_tokens=0,
            cache_read_tokens=0,
            cost_usd=0,
        ),
        patch_sha256=digest,
        patch_applied=False,
    )


def _default_verifier_result() -> VerifierResult:
    return VerifierResult(
        outcome=VerifierOutcome.PASSED,
        command_summary="fake verifier",
        exit_code=0,
        output_digest=hashlib.sha256(b"fake verifier").hexdigest(),
        output_preview="fake verifier passed",
    )
