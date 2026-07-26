from __future__ import annotations

from lion_code.context import estimate_messages_tokens
from lion_code.core.messages import (
    AssistantMessage,
    ImageContent,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from lion_code.memory_runtime import (
    MemoryContextInjector,
    MemoryContextPolicy,
    MemoryOverlay,
)


def _overlay(path: str = "project.md", content: str = "remember this") -> MemoryOverlay:
    return MemoryOverlay(path, content, len(content.encode("utf-8")))


def test_overlay_is_ephemeral_and_each_projection_contains_one_block() -> None:
    messages = [UserMessage(content="question")]
    snapshot = messages[0].model_dump(mode="json")
    injector = MemoryContextInjector()

    first, first_report = injector.inject(messages, [_overlay()])
    second, second_report = injector.inject(messages, [_overlay()])

    assert messages[0].model_dump(mode="json") == snapshot
    assert "<relevant-memory>" not in messages[0].text
    assert first[-1].text.count("<relevant-memory>") == 1
    assert second[-1].text.count("<relevant-memory>") == 1
    assert first_report.injected_paths == second_report.injected_paths == ("project.md",)


def test_multimodal_user_content_keeps_the_image() -> None:
    image = ImageContent(data="encoded", mime_type="image/png")
    messages = [UserMessage(content=[TextContent(text="look"), image])]

    projected, _ = MemoryContextInjector().inject(messages, [_overlay()])

    assert projected[0].content[1] == image
    assert projected[0].content[1] is not messages[0].content[1]
    assert "<relevant-memory>" in projected[0].text


def test_overlay_never_splits_tool_call_and_result() -> None:
    call = AssistantMessage(
        content=[ToolCall(id="call-1", name="read_file", arguments={})],
        stop_reason="toolUse",
    )
    injector = MemoryContextInjector()

    unresolved, report = injector.inject([call], [_overlay()])
    assert len(unresolved) == 1
    assert report.skipped_paths == ("project.md",)

    result = ToolResultMessage(
        tool_call_id="call-1",
        tool_name="read_file",
        content="result",
    )
    complete, report = injector.inject([call, result], [_overlay()])
    assert [message.role for message in complete] == [
        "assistant",
        "toolResult",
        "user",
    ]
    assert report.injected_paths == ("project.md",)


def test_injection_respects_byte_and_final_token_budgets() -> None:
    injector = MemoryContextInjector(
        MemoryContextPolicy(max_active_memories=3, max_injection_bytes=5)
    )
    messages = [UserMessage(content="question")]

    projected, report = injector.inject(
        messages,
        [_overlay("a.md", "1234"), _overlay("b.md", "5678")],
    )
    assert report.injected_paths == ("a.md",)
    assert report.skipped_paths == ("b.md",)
    assert "a.md" in projected[-1].text

    baseline_tokens = estimate_messages_tokens(messages)
    projected, report = injector.inject(
        messages,
        [_overlay("large.md", "x" * 100)],
        max_tokens=baseline_tokens,
    )
    assert projected[0].text == "question"
    assert report.skipped_paths == ("large.md",)


def test_duplicate_overlay_path_is_injected_once() -> None:
    projected, report = MemoryContextInjector().inject(
        [UserMessage(content="question")],
        [_overlay(), _overlay()],
    )

    assert projected[-1].text.count("## project.md") == 1
    assert report.injected_paths == ("project.md",)
    assert report.skipped_paths == ("project.md",)
