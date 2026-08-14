"""PR0 Kernel Event Stream contract tests.

Verifies that the Kernel event contract (``core/events.py`` + ``core/provider_events.py``)
can express all ten events the PR0 contract requires, that the new contract events
serialize/round-trip through the discriminated union, that the loop actually emits
``TurnFailedEvent`` / ``CancelledEvent``, and that the contract modules stay free of
cross-layer dependencies (so a future Supervisor can subscribe without reaching into
Agent internals).
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from lion_code.core import (
    AgentHarness,
    AgentHarnessConfig,
    CancelledEvent,
    CompactionCompletedEvent,
    CompactionStartedEvent,
    ToolExecutionEndEvent,
    TurnEndEvent,
    TurnFailedEvent,
    TurnStartEvent,
)
from lion_code.core import events as kernel_events
from lion_code.core.cancellation import CancellationToken
from lion_code.core.messages import UserMessage
from lion_code.core.provider_events import (
    AssistantStartEvent,
    TextDeltaEvent,
    ToolCallEndEvent,
)

from .fakes import FakeProvider

_SOURCE_ROOT = Path(__file__).resolve().parents[2] / "lion_code"

# The ten contract events from the PR0 spec, mapped to their Kernel expression.
# These are the events a Supervisor may subscribe to via the public contract.
CONTRACT_EVENTS: dict[str, type[kernel_events.WireModel]] = {
    "TurnStarted": TurnStartEvent,
    "ModelStarted": AssistantStartEvent,
    "ModelDelta": TextDeltaEvent,
    "ToolCallRequested": ToolCallEndEvent,
    "ToolCallCompleted": ToolExecutionEndEvent,
    "CompactionStarted": CompactionStartedEvent,
    "CompactionCompleted": CompactionCompletedEvent,
    "TurnCompleted": TurnEndEvent,
    "TurnFailed": TurnFailedEvent,
    "Cancelled": CancelledEvent,
}

# Layers a Kernel contract module must never import (Supervisor dependency is one-way).
_FORBIDDEN_IMPORTS = (
    "lion_code.agent",
    "lion_code.agent_runtime",
    "lion_code.tooling",
    "lion_code.providers",
    "lion_code.session_runtime",
    "lion_code.application",
    "lion_code.tui",
    "lion_code.capabilities",
    "lion_code.memory_runtime",
    "lion_code.plan_runtime",
    "lion_code.skill_runtime",
    "lion_code.subagent_runtime",
    "lion_code.autonomy_runtime",
    "lion_code.dream",
    "lion_code.learning_runtime",
    "lion_code.composition",
)


def _import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name)
    return roots


def test_all_ten_contract_events_are_expressible() -> None:
    for name, cls in CONTRACT_EVENTS.items():
        assert cls is not None, f"contract event {name} has no Kernel expression"
        assert cls.model_fields["type"].annotation, f"{name} missing discriminator"


@pytest.mark.parametrize("name", list(CONTRACT_EVENTS))
def test_contract_event_type_is_discriminated(name: str) -> None:
    wire = {
        "TurnStarted": "turn_start",
        "ModelStarted": "start",
        "ModelDelta": "text_delta",
        "ToolCallRequested": "toolcall_end",
        "ToolCallCompleted": "tool_execution_end",
        "CompactionStarted": "compaction_started",
        "CompactionCompleted": "compaction_completed",
        "TurnCompleted": "turn_end",
        "TurnFailed": "turn_failed",
        "Cancelled": "cancelled",
    }[name]
    assert CONTRACT_EVENTS[name].model_fields["type"].default == wire


def test_new_contract_events_round_trip_via_union() -> None:
    samples = [
        TurnFailedEvent(message=UserMessage(content="boom")),
        CancelledEvent(),
        CompactionStartedEvent(reason="threshold"),
        CompactionCompletedEvent(reason="overflow", aborted=True),
    ]
    adapter: TypeAdapter = TypeAdapter(kernel_events.AgentEvent)
    for event in samples:
        payload = event.model_dump()
        parsed = adapter.validate_python(payload)
        assert type(parsed) is type(event)
        rebuilt = type(event).model_validate(payload)
        assert rebuilt == event


def test_kernel_event_contract_has_no_cross_layer_imports() -> None:
    # A future Supervisor subscribes to core.events / core.provider_events. These
    # modules must stay Kernel-only so that dependency stays one-way.
    for name in ("core/events.py", "core/provider_events.py"):
        roots = _import_roots(_SOURCE_ROOT / name)
        violations = [r for r in roots if r in _FORBIDDEN_IMPORTS]
        assert not violations, f"{name} imports non-Kernel modules: {violations}"


def test_error_run_emits_turn_failed() -> None:
    from lion_code.core.messages import AssistantMessage
    from lion_code.core.provider_events import AssistantErrorEvent

    async def run() -> list[object]:
        provider = FakeProvider(
            [
                AssistantErrorEvent(
                    reason="error",
                    error=AssistantMessage(model="fake", content=[]),
                )
            ]
        )
        harness = AgentHarness(
            AgentHarnessConfig(provider=provider, model="fake", system="test")
        )
        return [event async for event in harness.prompt("hello")]

    events = asyncio.run(run())
    assert any(isinstance(e, TurnFailedEvent) for e in events)
    assert type(events[-1]).__name__ == "AgentEndEvent"


def test_cancelled_run_emits_cancelled() -> None:
    async def run() -> list[object]:
        token = CancellationToken()
        provider = FakeProvider([])
        harness = AgentHarness(
            AgentHarnessConfig(provider=provider, model="fake", system="test"),
            cancellation=token,
        )
        token.cancel()
        return [event async for event in harness.prompt("hello")]

    events = asyncio.run(run())
    assert any(isinstance(e, CancelledEvent) for e in events)
