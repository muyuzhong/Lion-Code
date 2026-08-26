from __future__ import annotations

import subprocess
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from lion_code.capabilities.agent_state import AgentStateLayer
from lion_code.capabilities.git_status import GitStatusLayer
from lion_code.context import (
    SUMMARY_HEADINGS,
    ContextManager,
    ContextRuntimeState,
    ContextView,
    ProviderContextCompactor,
    build_compaction_request,
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


def _call(
    index: int,
    *,
    path: str = "a.py",
    name: str = "read_file",
) -> AssistantMessage:
    return AssistantMessage(
        content=[
            ToolCall(
                id=f"call-{index}",
                name=name,
                arguments={"file_path": path},
            )
        ],
        stop_reason="toolUse",
    )


def test_context_view_projects_bounded_activity_and_recent_failures() -> None:
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
    assert [(trace.name, trace.count) for trace in view.tool_totals] == [
        ("read_file", 1),
        ("run_shell", 1),
    ]
    assert [trace.summary for trace in view.recent_tool_calls] == [
        "read_file(path=a.py)",
        "run_shell(command=pytest)",
    ]
    assert view.repeated_tool_calls == ()
    assert view.other_tool_calls == 0
    assert not hasattr(view, "tool_trace")
    assert view.recent_failures == ("run_shell: pytest failed, exit=1",)

    arguments["file_path"] = "changed.py"
    assert view.recent_tool_calls[0].summary == "read_file(path=a.py)"
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


def test_context_view_bounds_tool_totals_recent_and_repeated_activity() -> None:
    messages = [
        *[_call(index, path="a.py") for index in range(4)],
        *[_call(index + 4, path="b.py") for index in range(3)],
        *[_call(index + 7, path="c.py", name="run_shell") for index in range(2)],
        _call(9, path="d.py", name="grep_search"),
        _call(10, path="e.py", name="write_file"),
    ]

    view = ContextView.from_messages(messages, current_time="now")

    assert [(trace.name, trace.count) for trace in view.tool_totals] == [
        ("read_file", 7),
        ("run_shell", 2),
        ("grep_search", 1),
    ]
    assert view.other_tool_calls == 1
    assert [trace.summary for trace in view.recent_tool_calls] == [
        "run_shell(path=c.py)",
        "grep_search(path=d.py)",
        "write_file(path=e.py)",
    ]
    assert [(trace.summary, trace.count) for trace in view.repeated_tool_calls] == [
        ("read_file(path=a.py)", 4),
        ("read_file(path=b.py)", 3),
        ("run_shell(path=c.py)", 2),
    ]
    assert len(view.tool_totals) <= 3
    assert len(view.recent_tool_calls) <= 3
    assert len(view.repeated_tool_calls) <= 3
    assert len(view.recent_failures) <= 3


def test_context_view_scans_only_the_latest_64_tool_calls() -> None:
    messages = [
        *[_call(index, path=f"old-{index}.py") for index in range(80)],
        *[
            _call(index + 80, path="src/app.py", name="grep_search")
            for index in range(64)
        ],
    ]
    original_messages = tuple(message.model_dump(mode="json") for message in messages)

    view = ContextView.from_messages(messages, current_time="now")

    assert [(trace.name, trace.count) for trace in view.tool_totals] == [
        ("grep_search", 64),
    ]
    assert view.other_tool_calls == 0
    assert [trace.summary for trace in view.recent_tool_calls] == [
        "grep_search(path=src/app.py)"
    ] * 3
    assert [(trace.summary, trace.count) for trace in view.repeated_tool_calls] == [
        ("grep_search(path=src/app.py)", 64),
    ]
    assert [message.model_dump(mode="json") for message in messages] == list(
        original_messages
    )


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
    assert "read_file: 4 calls" in rendered
    assert "read_file(path=a.py) ×4" in rendered
    assert "Recent tool totals:" in rendered
    assert "Recent activity:" in rendered
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
    assert "Dirty files: 1" in first
    assert "- a.py" in first
    assert "- b.py" in second
    assert git_output.call_count == 4


def test_git_status_layer_ignores_ancestor_repository(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    view = ContextView.from_messages([], current_time="now")

    with patch("lion_code.capabilities.git_status.capability.subprocess.run") as run:
        rendered = GitStatusLayer().render(view)

    assert "Branch: (detached)" in rendered
    assert "Dirty files: 0" in rendered
    assert "- clean" in rendered
    run.assert_not_called()


def test_git_status_layer_does_not_capture_subprocess_pipes(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    outputs = iter(("main\n", "M  a.py\n"))

    def run_git(*_args, stdin, stdout, stderr, **_kwargs):
        assert stdin is subprocess.DEVNULL
        assert stdout is not subprocess.PIPE
        assert stderr is subprocess.DEVNULL
        stdout.write(next(outputs))
        stdout.flush()
        return subprocess.CompletedProcess([], 0)

    with patch(
        "lion_code.capabilities.git_status.capability.subprocess.run",
        side_effect=run_git,
    ):
        rendered = GitStatusLayer().render(
            ContextView.from_messages([], current_time="now")
        )

    assert "Branch: main" in rendered
    assert "- a.py" in rendered


def test_git_status_layer_bounds_dirty_file_list() -> None:
    view = ContextView.from_messages([], current_time="now")
    with patch(
        "lion_code.capabilities.git_status.capability._git_output",
        side_effect=["main", "\n".join(f" M {name}.py" for name in "abcde")],
    ):
        rendered = GitStatusLayer().render(view)

    assert "Dirty files: 5" in rendered
    assert "- a.py" in rendered
    assert "- b.py" in rendered
    assert "- c.py" in rendered
    assert "- ... 2 more" in rendered
    assert "- d.py" not in rendered


@pytest.mark.parametrize(
    ("status", "expected", "excluded"),
    (
        ("", ("Dirty files: 0", "- clean"), ("...",)),
        (
            "R  old.py -> z.py\n M a.py\n?? b.py",
            ("Dirty files: 3", "- a.py", "- b.py", "- z.py"),
            ("old.py", "more"),
        ),
    ),
)
def test_git_status_layer_handles_clean_exact_limit_and_rename(
    status: str,
    expected: tuple[str, ...],
    excluded: tuple[str, ...],
) -> None:
    view = ContextView.from_messages([], current_time="now")
    with patch(
        "lion_code.capabilities.git_status.capability._git_output",
        side_effect=["main", status],
    ):
        rendered = GitStatusLayer().render(view)

    assert all(value in rendered for value in expected)
    assert all(value not in rendered for value in excluded)


class _RecordingProvider:
    def __init__(self) -> None:
        self.messages: list[list] = []

    def stream_response(self, **kwargs):
        self.messages.append(list(kwargs["messages"]))

        async def events():
            yield AssistantDoneEvent(
                reason="stop",
                message=AssistantMessage(
                    content=[
                        TextContent(
                            text="\n\n".join(
                                f"{heading}\ncontent" for heading in SUMMARY_HEADINGS
                            )
                        )
                    ]
                ),
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
    assert await compactor.summarize(
        build_compaction_request(
            history=tuple(source),
            recent_context=(),
            requested_objective=None,
            effective_window_tokens=2_000,
            input_ratio=0.85,
        )
    ) == "\n\n".join(f"{heading}\ncontent" for heading in SUMMARY_HEADINGS)
    assert all(message.text != state_text for message in provider.messages[0])
