"""Non-destructive helpers for deriving provider-bound message projections."""

from __future__ import annotations

from collections.abc import Iterable

from lion_code.core.messages import AgentMessage, TextContent, ToolResultMessage


def project_messages(messages: Iterable[AgentMessage]) -> list[AgentMessage]:
    """Return deep copies so active-context rewrites cannot alter durable history."""

    return [message.model_copy(deep=True) for message in messages]


def replace_tool_result_text(message: ToolResultMessage, text: str) -> None:
    """Replace text blocks while retaining any non-text result content in order."""

    replacement = TextContent(text=text)
    updated = []
    inserted = False
    for block in message.content:
        if isinstance(block, TextContent):
            if not inserted:
                updated.append(replacement)
                inserted = True
            continue
        updated.append(block)
    if not inserted:
        updated.insert(0, replacement)
    message.content = updated
