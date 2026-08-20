from __future__ import annotations

from pathlib import Path

import pytest

from lion_code.context import ContextManager, ModelLimitsResolver
from lion_code.core import UserMessage
from lion_code.runtime.context import ContextRuntime
from lion_code.runtime.execution import ExecutionControl
from lion_code.usage import UsageLedger


class _CapturingCompactor:
    def __init__(self) -> None:
        self.request = None

    async def summarize(self, request) -> str:
        self.request = request
        return "summary"


class _PlanView:
    def __init__(self, *, active: bool, file_path: Path | None = None) -> None:
        self.is_active = active
        self.file_path = file_path


def _runtime(plan_view=None) -> tuple[ContextRuntime, _CapturingCompactor]:
    compactor = _CapturingCompactor()
    runtime = ContextRuntime(
        context_manager=ContextManager(),
        context_compactor=compactor,
        model_limits_resolver=ModelLimitsResolver(),
        usage=UsageLedger(),
        execution=ExecutionControl(),
        initial_effective_window=1_000,
        plan_view=plan_view,
    )
    return runtime, compactor


@pytest.mark.asyncio
async def test_context_runtime_assembles_request_with_objective_and_plan(
    tmp_path,
) -> None:
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("Keep session replay append-only.", encoding="utf-8")
    runtime, compactor = _runtime(
        _PlanView(active=True, file_path=plan_path),
    )
    history = (UserMessage(content="old history"),)
    recent = (UserMessage(content="recent context"),)

    assert (
        await runtime.summarize(
            history,
            recent_context=recent,
            objective="finish structured compaction",
        )
        == "summary"
    )

    assert compactor.request.history == history
    assert compactor.request.recent_context == recent
    assert compactor.request.objective == (
        "Current task:\nfinish structured compaction\n\n"
        f"Active plan ({plan_path}):\nKeep session replay append-only."
    )


@pytest.mark.asyncio
async def test_context_runtime_falls_back_to_recent_user_goal() -> None:
    runtime, compactor = _runtime(_PlanView(active=False))

    await runtime.summarize(
        (UserMessage(content="old history"),),
        recent_context=(UserMessage(content="continue the parser work"),),
    )

    assert compactor.request.objective == "Current task:\ncontinue the parser work"


@pytest.mark.asyncio
async def test_context_runtime_keeps_objective_empty_when_unknown(tmp_path) -> None:
    runtime, compactor = _runtime(
        _PlanView(active=True, file_path=tmp_path / "missing-plan.md"),
    )

    await runtime.summarize((), recent_context=())

    assert compactor.request.objective is None
