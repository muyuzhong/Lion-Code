from __future__ import annotations

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


def _runtime() -> tuple[ContextRuntime, _CapturingCompactor]:
    compactor = _CapturingCompactor()
    runtime = ContextRuntime(
        context_manager=ContextManager(),
        context_compactor=compactor,
        model_limits_resolver=ModelLimitsResolver(),
        usage=UsageLedger(),
        execution=ExecutionControl(),
        initial_effective_window=1_000,
    )
    return runtime, compactor


@pytest.mark.asyncio
async def test_context_runtime_assembles_bounded_request_with_objective() -> None:
    runtime, compactor = _runtime()
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

    assert compactor.request.history_projection == "[user]\nold history"
    assert compactor.request.recent_context_hint == ""
    assert compactor.request.objective == "Current task:\nfinish structured compaction"
    assert compactor.request.input_budget_tokens == 850


@pytest.mark.asyncio
async def test_context_runtime_falls_back_to_recent_user_goal() -> None:
    runtime, compactor = _runtime()

    await runtime.summarize(
        (UserMessage(content="old history"),),
        recent_context=(UserMessage(content="continue the parser work"),),
    )

    assert compactor.request.objective == "Current task:\ncontinue the parser work"


@pytest.mark.asyncio
async def test_context_runtime_keeps_objective_empty_when_unknown() -> None:
    runtime, compactor = _runtime()

    await runtime.summarize((), recent_context=())

    assert compactor.request.objective is None
