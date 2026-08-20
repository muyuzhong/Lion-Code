"""容器内 Agent worker：复用 Agent.run 与 Core typed event 订阅。"""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Awaitable, Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from lion_code.adapters.coding_session_backend import CodingSessionBackendAdapter
from lion_code.composition.full_product import build_full_coding_backend
from lion_code.session_runtime import SessionRepository

from .backend import AgentExecutionRequest
from .models import AgentRunSummary, WorkerResult, WorkerStatus
from .trace import TraceRecorder, redact_text


AgentFactory = Callable[..., CodingSessionBackendAdapter]


async def run_agent_worker(
    request: AgentExecutionRequest,
    *,
    agent_factory: AgentFactory = build_full_coding_backend,
    trace_recorder: TraceRecorder | None = None,
) -> WorkerResult:
    """在 Agent workspace 中运行一次根 Agent，并返回不含 session/凭证的结果。

    该函数只在容器内 worker 使用。调用方必须提供 workspace 之外的 session_root，
    否则拒绝运行，避免 JSONL 进入待验收 patch。
    """

    workspace = request.agent_workspace.resolve()
    if not workspace.is_dir():
        raise ValueError(f"Agent workspace does not exist: {workspace}")
    session_dir = _session_dir_for(request)
    _require_external_session_dir(session_dir, workspace)
    session_repository = SessionRepository(session_dir)
    recorder = trace_recorder or TraceRecorder()
    agent: Agent | None = None
    unsubscribe: Callable[[], None] | None = None
    result: WorkerResult | None = None
    try:
        with _working_directory(workspace):
            agent = agent_factory(
                permission_mode=request.manifest.profile.permission_mode,
                model=request.manifest.profile.model,
                max_cost_usd=(
                    request.manifest.profile.budget_usd
                    if request.manifest.profile.budget_usd > 0
                    else None
                ),
                max_turns=request.manifest.profile.max_turns,
                confirm_fn=_auto_confirm,
                session_repository=session_repository,
                terminal_output=False,
            )
            unsubscribe = agent.subscribe(recorder.record)
            run_result = await agent.run(
                request.task.public_prompt,
                timeout=request.manifest.timeout_seconds,
            )
        result = WorkerResult(
            status=WorkerStatus.COMPLETED,
            agent_run=_agent_run_summary(run_result),
            trace_summary=recorder.summary(),
        )
    except asyncio.CancelledError:
        raise
    except asyncio.TimeoutError:
        result = WorkerResult(
            status=WorkerStatus.TIMEOUT,
            error_summary="worker timeout",
            trace_summary=recorder.summary(),
        )
    except Exception as error:
        summary, _ = redact_text(str(error) or error.__class__.__name__)
        result = WorkerResult(
            status=WorkerStatus.ERROR,
            error_summary=summary,
            trace_summary=recorder.summary(),
        )
    finally:
        if unsubscribe is not None:
            unsubscribe()
        if agent is not None:
            try:
                await agent.close()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                summary, _ = redact_text(str(error) or error.__class__.__name__)
                result = WorkerResult(
                    status=WorkerStatus.ERROR,
                    error_summary=f"agent close failed: {summary}",
                    trace_summary=recorder.summary(),
                )
    assert result is not None
    return result


def _agent_run_summary(run_result: Any) -> AgentRunSummary:
    final_text = str(getattr(run_result, "final_text", ""))
    preview, _ = redact_text(final_text, max_length=320)
    raw_error = getattr(run_result, "error", None)
    error_summary = None
    if raw_error:
        error_summary, _ = redact_text(str(raw_error), max_length=320)
    return AgentRunSummary(
        final_text_digest=hashlib.sha256(final_text.encode("utf-8")).hexdigest(),
        final_text_preview=preview,
        stop_reason=str(getattr(run_result, "stop_reason", "unknown")),
        turns=int(getattr(run_result, "turns", 0)),
        wall_time_seconds=float(getattr(run_result, "wall_time_seconds", 0)),
        input_tokens=int(getattr(run_result, "input_tokens", 0)),
        output_tokens=int(getattr(run_result, "output_tokens", 0)),
        cache_read_tokens=int(getattr(run_result, "cache_read_tokens", 0)),
        cost_usd=float(getattr(run_result, "cost_usd", 0)),
        error_summary=error_summary,
    )


def _session_dir_for(request: AgentExecutionRequest) -> Path:
    return (
        request.session_root.resolve()
        / request.manifest.run_id
        / request.task.task_id
        / f"attempt-{request.attempt}"
    )


def _require_external_session_dir(session_dir: Path, workspace: Path) -> None:
    if _is_within(session_dir, workspace) or _is_within(workspace, session_dir):
        raise ValueError("Evaluation session directory must be outside agent workspace")


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


async def _auto_confirm(_prompt: str) -> bool:
    """容器边界内的评测使用显式自动确认；host fallback 不调用本 worker。"""

    return True


@contextmanager
def _working_directory(path: Path):
    """Agent 的 ToolContext 当前从进程 cwd 读取；worker 是单任务容器进程。"""

    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)
