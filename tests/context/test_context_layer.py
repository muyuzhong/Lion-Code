from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from lion_code.capabilities.agent_state import AgentStateLayer
from lion_code.capabilities.git_status import GitStatusLayer
from lion_code.context import (
    ContextManager,
    ContextRuntimeState,
    ContextView,
    ProviderContextCompactor,
    estimate_messages_tokens,
)
from lion_code.context.projector import project_messages
from lion_code.core import (
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from lion_code.core.provider_events import AssistantDoneEvent
from lion_code.core.session import JsonlSessionStorage
from lion_code.session_runtime import SessionRecorder


def _call(index: int, *, path: str = "a.py") -> AssistantMessage:
    return AssistantMessage(
        content=[
            ToolCall(
                id=f"call-{index}",
                name="read_file",
                arguments={"file_path": path},
            )
        ],
        stop_reason="toolUse",
    )


def test_context_view_projects_tool_trace_and_recent_failures() -> None:
    arguments = {"file_path": "a.py"}
    messages = [
        AssistantMessage(
            content=[
                ToolCall(
                    id="call-1",
                    name="read_file",
                    arguments=arguments,
                )
            ],
            stop_reason="toolUse",
        ),
        ToolResultMessage(
            tool_call_id="call-1",
            tool_name="read_file",
            content=[TextContent(text="ok")],
        ),
        AssistantMessage(
            content=[
                ToolCall(
                    id="call-2",
                    name="run_shell",
                    arguments={"command": "pytest"},
                )
            ],
            stop_reason="toolUse",
        ),
        ToolResultMessage(
            tool_call_id="call-2",
            tool_name="run_shell",
            content=[TextContent(text="pytest failed\nTraceback omitted")],
            details={"exit_code": 1},
            is_error=True,
        ),
    ]

    view = ContextView.from_messages(
        messages,
        ContextRuntimeState(
            effective_window_tokens=1_000,
            last_prompt_tokens=250,
            now=0,
        ),
        current_time="2026-08-20T12:00:00+00:00",
        compaction_required=True,
    )

    assert view.current_time == "2026-08-20T12:00:00+00:00"
    assert view.context_utilization.used_tokens == 250
    assert view.context_utilization.limit_tokens == 1_000
    assert view.context_utilization.percentage == 25.0
    assert view.context_utilization.compaction == "required"
    assert [trace.summary for trace in view.tool_trace] == [
        "read_file(path=a.py)",
        "run_shell(command=pytest)",
    ]
    assert view.recent_failures == ("run_shell: pytest failed, exit=1",)

    arguments["file_path"] = "changed.py"
    assert view.tool_trace[0].summary == "read_file(path=a.py)"
    with pytest.raises(FrozenInstanceError):
        view.current_time = "changed"  # type: ignore[misc]


def test_context_view_keeps_only_last_three_failure_lines() -> None:
    messages = [
        ToolResultMessage(
            tool_call_id=f"call-{index}",
            tool_name="run_shell",
            content=[
                TextContent(
                    text=(f"failure-{index}\nTraceback (most recent call last):")
                )
            ],
            is_error=True,
        )
        for index in range(4)
    ]

    view = ContextView.from_messages(messages, current_time="now")

    assert view.recent_failures == (
        "run_shell: failure-1",
        "run_shell: failure-2",
        "run_shell: failure-3",
    )
    assert all("Traceback" not in failure for failure in view.recent_failures)


class _Layer:
    def __init__(self, layer_id: str, fragment: str) -> None:
        self.layer_id = layer_id
        self.fragment = fragment
        self.views: list[ContextView] = []

    def render(self, view: ContextView) -> str:
        self.views.append(view)
        return self.fragment


def test_context_manager_appends_one_sorted_transient_state_message() -> None:
    late = _Layer("z-layer", "Z")
    early = _Layer("a-layer", "A")
    source = [_call(0)]

    prepared = ContextManager(
        context_layers=lambda: (late, early),
    ).prepare(
        source,
        ContextRuntimeState(effective_window_tokens=1_000, last_prompt_tokens=100),
    )

    assert len(prepared.messages) == len(source) + 1
    state_message = prepared.messages[-1]
    assert isinstance(state_message, UserMessage)
    assert state_message.text == "<agent-state>\nA\n\nZ\n</agent-state>"
    assert state_message.role == "user"
    assert len(early.views) == 1
    assert len(late.views) == 1
    assert all(message.text != state_message.text for message in source)
    assert prepared.estimated_tokens == estimate_messages_tokens(prepared.messages)


def test_no_context_layers_preserves_projection_and_token_estimate() -> None:
    source = [_call(0), UserMessage(content="keep this")]
    state = ContextRuntimeState(effective_window_tokens=1_000, last_prompt_tokens=100)
    expected = tuple(project_messages(source))

    prepared = ContextManager().prepare(source, state)

    assert [message.model_dump(mode="json") for message in prepared.messages] == [
        message.model_dump(mode="json") for message in expected
    ]
    assert prepared.estimated_tokens == estimate_messages_tokens(expected)
    assert not any("<agent-state>" in message.text for message in prepared.messages)


def test_agent_state_groups_repeated_tool_activity() -> None:
    view = ContextView.from_messages(
        [_call(index) for index in range(4)],
        ContextRuntimeState(effective_window_tokens=10_000, last_prompt_tokens=500),
        current_time="now",
    )

    rendered = AgentStateLayer().render(view)

    assert "Time: now" in rendered
    assert "Context: 500 / 10k tokens (5.0%)" in rendered
    assert "read_file(path=a.py) ×4" in rendered
    assert "Recent failures:" in rendered


def test_git_status_layer_reads_workspace_on_every_render() -> None:
    view = ContextView.from_messages([], current_time="now")
    with patch(
        "lion_code.capabilities.git_status.capability._git_output",
        side_effect=["main", " M a.py", "main", "?? b.py"],
    ) as git_output:
        first = GitStatusLayer().render(view)
        second = GitStatusLayer().render(view)

    assert "Branch: main" in first
    assert "- a.py" in first
    assert "- b.py" in second
    assert git_output.call_count == 4


class _RecordingProvider:
    def __init__(self) -> None:
        self.messages: list[list] = []

    def stream_response(self, **kwargs):
        self.messages.append(list(kwargs["messages"]))

        async def events():
            yield AssistantDoneEvent(
                reason="stop",
                message=AssistantMessage(content=[TextContent(text="summary")]),
            )

        return events()


@pytest.mark.asyncio
async def test_prepared_state_is_not_canonical_jsonl_compaction_or_compactor_input(
    tmp_path: Path,
) -> None:
    source = [UserMessage(content="canonical")]
    prepared = ContextManager(
        context_layers=lambda: (_Layer("state", "Ephemeral state"),),
    ).prepare(
        source,
        ContextRuntimeState(effective_window_tokens=1_000, last_prompt_tokens=100),
    )
    state_text = prepared.messages[-1].text
    assert state_text.startswith("<agent-state>")
    assert all(message.text != state_text for message in source)

    storage = JsonlSessionStorage(tmp_path / "session.jsonl")
    recorder = SessionRecorder(
        session_id="session",
        model="model",
        thinking_level="disabled",
        cwd=tmp_path,
        storage=storage,
    )
    entry = await recorder.record_message(source[0])
    await recorder.record_compaction(
        summary="summary",
        replaces_entry_ids=[entry.id],
    )
    jsonl = (tmp_path / "session.jsonl").read_text(encoding="utf-8")
    assert state_text not in jsonl
    assert "<agent-state>" not in jsonl

    provider = _RecordingProvider()
    compactor = ProviderContextCompactor(
        provider=provider,
        get_model=lambda: "model",
    )
    assert await compactor.summarize(tuple(source)) == "summary"
    assert all(message.text != state_text for message in provider.messages[0])
