from __future__ import annotations

from lion_code.context import ContextManager, ContextRuntimeState
from lion_code.core import AssistantMessage, TextContent, ToolCall, ToolResultMessage


def _messages(specs: list[tuple[str, str]]) -> list:
    messages = []
    for index, (tool_name, path) in enumerate(specs):
        call_id = f"call-{index}"
        messages.extend(
            [
                AssistantMessage(
                    content=[
                        ToolCall(
                            id=call_id,
                            name=tool_name,
                            arguments={"file_path": path},
                        )
                    ],
                    stop_reason="toolUse",
                ),
                ToolResultMessage(
                    tool_call_id=call_id,
                    tool_name=tool_name,
                    content=[TextContent(text=f"result-{index}-" + "x" * 200)],
                ),
            ]
        )
    return messages


def _manager() -> ContextManager:
    return ContextManager(is_snippable_tool=lambda _name: True)


def _result_texts(prepared) -> list[str]:
    return [
        message.text
        for message in prepared.messages
        if isinstance(message, ToolResultMessage)
    ]


def test_snip_keeps_recent_three_results() -> None:
    prepared = _manager().prepare(
        _messages([("run_shell", str(index)) for index in range(6)]),
        ContextRuntimeState(100, 65),
    )

    texts = _result_texts(prepared)
    assert texts[:3] == [_manager().policy.snip_placeholder] * 3
    assert all(text.startswith("result-") for text in texts[-3:])


def test_snip_keeps_latest_read_of_each_file() -> None:
    specs = [
        ("read_file", "same.py"),
        ("read_file", ".\\same.py"),
        ("run_shell", "2"),
        ("run_shell", "3"),
        ("run_shell", "4"),
        ("run_shell", "5"),
        ("run_shell", "6"),
    ]
    prepared = _manager().prepare(_messages(specs), ContextRuntimeState(100, 65))

    texts = _result_texts(prepared)
    assert texts[0] == _manager().policy.snip_placeholder
    assert texts[1].startswith("result-1-")
    assert texts[-3:] == [
        "result-4-" + "x" * 200,
        "result-5-" + "x" * 200,
        "result-6-" + "x" * 200,
    ]


def test_hot_cache_delays_snip_below_override() -> None:
    messages = _messages([("run_shell", str(index)) for index in range(6)])
    prepared = _manager().prepare(
        messages,
        ContextRuntimeState(100, 65, last_model_call_at=999, now=1_000),
    )

    assert not any(action.type == "snip_tool_result" for action in prepared.actions)
    assert _result_texts(prepared)[0].startswith("result-0-")


def test_hot_cache_is_overridden_at_high_utilization() -> None:
    prepared = _manager().prepare(
        _messages([("run_shell", str(index)) for index in range(6)]),
        ContextRuntimeState(100, 75, last_model_call_at=999, now=1_000),
    )

    assert any(action.type == "snip_tool_result" for action in prepared.actions)


def test_cold_cache_clears_old_results_without_high_utilization() -> None:
    prepared = _manager().prepare(
        _messages([("run_shell", str(index)) for index in range(6)]),
        ContextRuntimeState(100, 10, last_model_call_at=600, now=1_000),
    )

    texts = _result_texts(prepared)
    assert texts[:3] == [_manager().policy.cleared_placeholder] * 3
    assert all(text.startswith("result-") for text in texts[-3:])
    assert sum(action.type == "clear_tool_result" for action in prepared.actions) == 3


def test_compaction_threshold_is_reported_without_replacing_messages() -> None:
    messages = _messages([("run_shell", "one")])

    prepared = _manager().prepare(messages, ContextRuntimeState(100, 85))

    assert prepared.compaction_required
    assert prepared.actions[-1].type == "request_compaction"
    assert len(prepared.messages) == len(messages)
