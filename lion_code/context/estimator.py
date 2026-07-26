"""Cheap deterministic token estimates for projected canonical messages."""

from __future__ import annotations

from collections.abc import Iterable

from lion_code.core.messages import AgentMessage


APPROXIMATE_CHARS_PER_TOKEN = 4


def estimate_messages_tokens(messages: Iterable[AgentMessage]) -> int:
    """Estimate serialized message tokens without importing a provider tokenizer."""

    chars = sum(
        len(message.model_dump_json(by_alias=True, exclude_none=True))
        for message in messages
    )
    if chars == 0:
        return 0
    return (chars + APPROXIMATE_CHARS_PER_TOKEN - 1) // APPROXIMATE_CHARS_PER_TOKEN
