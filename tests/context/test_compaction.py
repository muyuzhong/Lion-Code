from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from lion_code.context import (
    COMPACTION_PROMPT_TEMPLATE,
    OBJECTIVE_UNAVAILABLE_MARKER,
    SUMMARY_SYSTEM_PROMPT,
    CompactionRequest,
    ProviderContextCompactor,
    resolve_compaction_objective,
)
from lion_code.core import AssistantMessage, TextContent, UserMessage
from lion_code.core.provider_events import (
    AssistantDoneEvent,
    AssistantErrorEvent,
    AssistantMessageEvent,
)


class _RecordingProvider:
    def __init__(self, event: AssistantMessageEvent) -> None:
        self.event = event
        self.calls = []

    def stream_response(
        self, *, model, system, messages, tools, signal=None
    ) -> AsyncIterator[AssistantMessageEvent]:
        self.calls.append((model, system, messages, tools, signal))

        async def stream():
            yield self.event

        return stream()


@pytest.mark.asyncio
async def test_provider_compactor_uses_canonical_stream_without_mutating_history() -> (
    None
):
    provider = _RecordingProvider(
        AssistantDoneEvent(
            reason="stop",
            message=AssistantMessage(content=[TextContent(text="  concise summary  ")]),
        )
    )
    messages = (UserMessage(content="original"),)
    compactor = ProviderContextCompactor(provider=provider, get_model=lambda: "fake")

    summary = await compactor.summarize(
        CompactionRequest(
            history=messages,
            recent_context=(UserMessage(content="recent background"),),
            objective="finish the compaction change",
        )
    )

    assert summary == "concise summary"
    assert messages[0].text == "original"
    model, system, projected, tools, signal = provider.calls[0]
    assert model == "fake"
    assert system == SUMMARY_SYSTEM_PROMPT
    assert projected[0] is not messages[0]
    assert "finish the compaction change" in projected[-1].text
    assert "recent background" in projected[-1].text
    assert projected[-1].text == COMPACTION_PROMPT_TEMPLATE.format(
        objective="finish the compaction change",
        recent_context="[user]\nrecent background",
    )
    assert tools == []
    assert signal is None


def test_compaction_request_freezes_message_collections() -> None:
    history = [UserMessage(content="history")]
    recent = [UserMessage(content="recent")]

    request = CompactionRequest(
        history=history,
        recent_context=recent,
        objective=None,
    )

    history.append(UserMessage(content="later"))
    recent.append(UserMessage(content="later"))

    assert request.history == (history[0],)
    assert request.recent_context == (recent[0],)
    assert request.objective is None


def test_compaction_prompt_has_fixed_sections_and_evidence_rules() -> None:
    sections = (
        "# Objective",
        "# Constraints",
        "# Decisions",
        "# Repository State",
        "# Findings",
        "# Failed Attempts",
        "# Completed Work",
        "# Remaining Work",
        "# Verification",
    )

    positions = [COMPACTION_PROMPT_TEMPLATE.index(section) for section in sections]

    assert positions == sorted(positions)
    assert "Coding Evidence" in COMPACTION_PROMPT_TEMPLATE
    assert "Evidence:" in COMPACTION_PROMPT_TEMPLATE
    assert "objective-unavailable marker" in COMPACTION_PROMPT_TEMPLATE


class _PlanView:
    def __init__(self, *, active: bool, file_path=None) -> None:
        self.is_active = active
        self.file_path = file_path


def test_objective_prefers_explicit_request_and_merges_active_plan(tmp_path) -> None:
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("Keep the summary append-only.", encoding="utf-8")

    objective = resolve_compaction_objective(
        requested_objective="Ship structured compaction",
        history=(UserMessage(content="old goal"),),
        recent_context=(UserMessage(content="recent goal"),),
        plan_view=_PlanView(active=True, file_path=plan_path),
    )

    assert objective == (
        "Current task:\nShip structured compaction\n\n"
        f"Active plan ({plan_path}):\nKeep the summary append-only."
    )


def test_objective_falls_back_to_recent_user_message_or_empty_marker(tmp_path) -> None:
    recent = (UserMessage(content="recent goal"),)

    assert (
        resolve_compaction_objective(
            requested_objective=None,
            history=(UserMessage(content="old goal"),),
            recent_context=recent,
            plan_view=_PlanView(active=False),
        )
        == "Current task:\nrecent goal"
    )

    assert (
        resolve_compaction_objective(
            requested_objective=None,
            history=(),
            recent_context=(),
            plan_view=_PlanView(active=True, file_path=tmp_path / "missing.md"),
        )
        is None
    )
    invalid_plan = tmp_path / "invalid-plan.md"
    invalid_plan.write_bytes(b"\xff")
    assert (
        resolve_compaction_objective(
            requested_objective=None,
            history=(),
            recent_context=(),
            plan_view=_PlanView(active=True, file_path=invalid_plan),
        )
        is None
    )
    assert OBJECTIVE_UNAVAILABLE_MARKER in COMPACTION_PROMPT_TEMPLATE.format(
        objective=OBJECTIVE_UNAVAILABLE_MARKER,
        recent_context="(none)",
    )


@pytest.mark.asyncio
async def test_provider_compactor_surfaces_provider_failure() -> None:
    provider = _RecordingProvider(
        AssistantErrorEvent(
            reason="error",
            error=AssistantMessage(stop_reason="error", error_message="failed"),
        )
    )
    compactor = ProviderContextCompactor(provider=provider, get_model=lambda: "fake")

    with pytest.raises(RuntimeError, match="failed"):
        await compactor.summarize(
            CompactionRequest(history=(UserMessage(content="original"),))
        )
