from __future__ import annotations

from lion_code.context import ContextManager, ContextRuntimeState
from lion_code.core import AssistantMessage, TextContent, ToolCall, ToolResultMessage


def _conversation(contents: list[str], *, tool_name: str = "read_file") -> list:
    messages = []
    for index, content in enumerate(contents):
        call_id = f"call-{index}"
        messages.extend(
            [
                AssistantMessage(
                    content=[
                        ToolCall(
                            id=call_id,
                            name=tool_name,
                            arguments={"file_path": f"file-{index}.py"},
                        )
                    ],
                    stop_reason="toolUse",
                ),
                ToolResultMessage(
                    tool_call_id=call_id,
                    tool_name=tool_name,
                    content=[TextContent(text=content)],
                ),
            ]
        )
    return messages


def _manager() -> ContextManager:
    return ContextManager(is_snippable_tool=lambda name: name == "read_file")


def test_prepare_does_not_modify_source_messages() -> None:
    messages = _conversation(["x" * 40_000 for _ in range(5)])
    snapshot = [message.model_dump(mode="json") for message in messages]

    prepared = _manager().prepare(
        messages,
        ContextRuntimeState(100, 80, last_model_call_at=0, now=1_000),
    )

    assert [message.model_dump(mode="json") for message in messages] == snapshot
    assert prepared.messages[1] is not messages[1]
    budget_actions = [
        action for action in prepared.actions if action.type == "budget_tool_result"
    ]
    assert len(budget_actions) == 5
    assert all(action.retained_chars <= 15_000 for action in budget_actions)


def test_tool_call_and_result_pairing_is_preserved() -> None:
    messages = _conversation(["x" * 10_000 for _ in range(8)])

    prepared = _manager().prepare(
        messages,
        ContextRuntimeState(100, 80, last_model_call_at=0, now=1_000),
    )

    call_ids = {
        call.id
        for message in prepared.messages
        if isinstance(message, AssistantMessage)
        for call in message.tool_calls
    }
    result_ids = {
        message.tool_call_id
        for message in prepared.messages
        if isinstance(message, ToolResultMessage)
    }
    assert call_ids == result_ids
    assert len(prepared.messages) == len(messages)


def test_error_and_non_snippable_results_are_preserved() -> None:
    messages = _conversation(["x" * 40_000, "y" * 40_000])
    error = messages[1]
    assert isinstance(error, ToolResultMessage)
    error.is_error = True
    other = messages[3]
    assert isinstance(other, ToolResultMessage)
    other.tool_name = "write_file"

    prepared = _manager().prepare(
        messages,
        ContextRuntimeState(100, 90, last_model_call_at=0, now=1_000),
    )

    assert prepared.messages[1].text == "x" * 40_000
    assert prepared.messages[3].text == "y" * 40_000
    assert not any(action.tool_call_id in {"call-0", "call-1"} for action in prepared.actions)


def test_canonical_result_policy_metadata_works_without_registry_callback() -> None:
    messages = _conversation(["x" * 200 for _ in range(6)], tool_name="custom_read")
    for message in messages:
        if isinstance(message, ToolResultMessage):
            message.details = {"result_policy": "snippable"}

    prepared = ContextManager().prepare(messages, ContextRuntimeState(100, 65))

    texts = [
        message.text
        for message in prepared.messages
        if isinstance(message, ToolResultMessage)
    ]
    assert texts[:3] == [ContextManager().policy.snip_placeholder] * 3
    assert all(text == "x" * 200 for text in texts[-3:])
