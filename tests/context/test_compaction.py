from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from lion_code.context import (
    COMPACTION_PROMPT_TEMPLATE,
    OBJECTIVE_UNAVAILABLE_MARKER,
    SUMMARY_HEADINGS,
    SUMMARY_SYSTEM_PROMPT,
    CompactionRequest,
    InvalidCompactionSummary,
    ProviderContextCompactor,
    build_compaction_request,
    estimate_compaction_input_tokens,
    estimate_text_tokens,
    resolve_compaction_objective,
)
from lion_code.context.compaction import HISTORY_OMITTED_MARKER
from lion_code.core import (
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from lion_code.core.provider_events import (
    AssistantDoneEvent,
    AssistantErrorEvent,
    AssistantMessageEvent,
)

VALID_SUMMARY = "\n\n".join(f"{heading}\ncontent" for heading in SUMMARY_HEADINGS)


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
            message=AssistantMessage(
                content=[TextContent(text=f"  {VALID_SUMMARY}  ")]
            ),
        )
    )
    messages = (UserMessage(content="original"),)
    compactor = ProviderContextCompactor(provider=provider, get_model=lambda: "fake")
    request = build_compaction_request(
        history=messages,
        recent_context=(),
        requested_objective="finish the compaction change",
        effective_window_tokens=2_000,
        input_ratio=0.85,
    )

    summary = await compactor.summarize(request)

    assert summary == VALID_SUMMARY
    assert messages[0].text == "original"
    model, system, projected, tools, signal = provider.calls[0]
    assert model == "fake"
    assert system == SUMMARY_SYSTEM_PROMPT
    assert len(projected) == 1
    assert "finish the compaction change" in projected[0].text
    assert projected[0].text == COMPACTION_PROMPT_TEMPLATE.format(
        history_projection="[user]\noriginal",
        objective="Current task:\nfinish the compaction change",
        recent_context_hint="(none)",
    )
    assert estimate_compaction_input_tokens(request) <= request.input_budget_tokens
    assert tools == []
    assert signal is None


def test_compaction_request_rejects_non_positive_budget() -> None:
    with pytest.raises(ValueError, match="input_budget_tokens"):
        CompactionRequest(
            history_projection="history",
            objective=None,
            recent_context_hint="",
            input_budget_tokens=0,
        )


def test_compaction_prompt_has_fixed_sections_and_evidence_rules() -> None:
    positions = [
        COMPACTION_PROMPT_TEMPLATE.index(section) for section in SUMMARY_HEADINGS
    ]

    assert positions == sorted(positions)
    assert "Coding Evidence" in COMPACTION_PROMPT_TEMPLATE
    assert "Evidence:" in COMPACTION_PROMPT_TEMPLATE
    assert "objective-unavailable marker" in COMPACTION_PROMPT_TEMPLATE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "summary",
    (
        "unstructured summary",
        VALID_SUMMARY + "\n\n# Objective\nduplicate",
        "\n\n".join(f"{heading}\ncontent" for heading in reversed(SUMMARY_HEADINGS)),
    ),
)
async def test_provider_compactor_rejects_invalid_summary_structure(summary) -> None:
    provider = _RecordingProvider(
        AssistantDoneEvent(
            reason="stop",
            message=AssistantMessage(content=[TextContent(text=summary)]),
        )
    )
    compactor = ProviderContextCompactor(provider=provider, get_model=lambda: "fake")

    with pytest.raises(InvalidCompactionSummary):
        await compactor.summarize(
            build_compaction_request(
                history=(UserMessage(content="original"),),
                recent_context=(),
                requested_objective=None,
                effective_window_tokens=2_000,
                input_ratio=0.85,
            )
        )


def test_objective_prefers_explicit_request_then_recent_and_history() -> None:
    assert (
        resolve_compaction_objective(
            requested_objective="Ship structured compaction",
            history=(UserMessage(content="old goal"),),
            recent_context=(UserMessage(content="recent goal"),),
        )
        == "Current task:\nShip structured compaction"
    )
    assert (
        resolve_compaction_objective(
            requested_objective=None,
            history=(UserMessage(content="old goal"),),
            recent_context=(UserMessage(content="recent goal"),),
        )
        == "Current task:\nrecent goal"
    )
    assert (
        resolve_compaction_objective(
            requested_objective=None,
            history=(UserMessage(content="old goal"),),
            recent_context=(),
        )
        == "Current task:\nold goal"
    )


def test_objective_uses_empty_marker_when_unknown() -> None:
    assert (
        resolve_compaction_objective(
            requested_objective=None,
            history=(),
            recent_context=(),
        )
        is None
    )
    assert OBJECTIVE_UNAVAILABLE_MARKER in COMPACTION_PROMPT_TEMPLATE.format(
        history_projection="(none)",
        objective=OBJECTIVE_UNAVAILABLE_MARKER,
        recent_context_hint="(none)",
    )


def test_compaction_request_bounds_the_complete_provider_input() -> None:
    history = tuple(
        UserMessage(content=f"old-{index}-" + "x" * 2_000) for index in range(12)
    )
    recent = (
        AssistantMessage(
            content=[
                TextContent(text="last conclusion " + "y" * 1_000),
                ToolCall(
                    id="call-1",
                    name="read_file",
                    arguments={"path": "lion_code/context/compaction.py"},
                ),
            ]
        ),
        ToolResultMessage(
            tool_call_id="call-1",
            tool_name="read_file",
            content="failed",
            is_error=True,
        ),
    )
    canonical = tuple(message.model_dump_json() for message in history + recent)

    request = build_compaction_request(
        history=history,
        recent_context=recent,
        requested_objective="finish " + "z" * 1_000,
        effective_window_tokens=2_000,
        input_ratio=0.85,
    )

    assert request.input_budget_tokens == 1_700
    assert estimate_compaction_input_tokens(request) <= request.input_budget_tokens
    assert estimate_text_tokens(request.objective or "") <= 85
    assert estimate_text_tokens(request.recent_context_hint) <= 85
    assert "budgeted" in request.history_projection
    assert request.history_projection.startswith("[user]\nold-0-")
    assert request.history_projection.endswith("x" * 10)
    assert canonical == tuple(message.model_dump_json() for message in history + recent)


def test_compaction_request_rejects_window_smaller_than_fixed_prompt() -> None:
    with pytest.raises(RuntimeError, match="Fixed context compaction prompt"):
        build_compaction_request(
            history=(),
            recent_context=(),
            requested_objective=None,
            effective_window_tokens=10,
            input_ratio=0.85,
        )


def test_oversized_history_uses_marker_when_no_history_content_fits() -> None:
    minimum_request = CompactionRequest(
        history_projection=HISTORY_OMITTED_MARKER,
        objective=None,
        recent_context_hint="",
        input_budget_tokens=1,
    )
    minimum_budget = estimate_compaction_input_tokens(minimum_request)
    effective_window = next(
        window
        for window in range(minimum_budget, minimum_budget * 2)
        if int(window * 0.85) == minimum_budget
    )

    request = build_compaction_request(
        history=(
            AssistantMessage(content=[TextContent(text="old history " + "x" * 10_000)]),
        ),
        recent_context=(),
        requested_objective=None,
        effective_window_tokens=effective_window,
        input_ratio=0.85,
    )

    assert "budgeted" in request.history_projection
    assert "old history" not in request.history_projection
    assert estimate_compaction_input_tokens(request) == minimum_budget


def test_oversized_history_fails_when_omission_marker_does_not_fit() -> None:
    marker_request = CompactionRequest(
        history_projection=HISTORY_OMITTED_MARKER,
        objective=None,
        recent_context_hint="",
        input_budget_tokens=1,
    )
    insufficient_budget = estimate_compaction_input_tokens(marker_request) - 1
    effective_window = next(
        window
        for window in range(insufficient_budget, insufficient_budget * 2)
        if int(window * 0.85) == insufficient_budget
    )

    with pytest.raises(RuntimeError, match="omission marker"):
        build_compaction_request(
            history=(
                AssistantMessage(
                    content=[TextContent(text="old history " + "x" * 10_000)]
                ),
            ),
            recent_context=(),
            requested_objective=None,
            effective_window_tokens=effective_window,
            input_ratio=0.85,
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
            build_compaction_request(
                history=(UserMessage(content="original"),),
                recent_context=(),
                requested_objective=None,
                effective_window_tokens=2_000,
                input_ratio=0.85,
            )
        )


@pytest.mark.asyncio
async def test_provider_compactor_rejects_empty_summary() -> None:
    provider = _RecordingProvider(
        AssistantDoneEvent(
            reason="stop",
            message=AssistantMessage(content=[]),
        )
    )
    compactor = ProviderContextCompactor(provider=provider, get_model=lambda: "fake")

    with pytest.raises(RuntimeError, match="produced no summary"):
        await compactor.summarize(
            build_compaction_request(
                history=(UserMessage(content="original"),),
                recent_context=(),
                requested_objective=None,
                effective_window_tokens=2_000,
                input_ratio=0.85,
            )
        )
