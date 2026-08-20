"""对 canonical 消息投影进行低成本、确定性的 token 估算。"""

from __future__ import annotations

from collections.abc import Iterable

from lion_code.core.messages import AgentMessage

APPROXIMATE_CHARS_PER_TOKEN = 4


def estimate_text_tokens(text: str) -> int:
    """按与消息估算相同的规则估算纯文本 token 数。"""

    return _estimate_chars(len(text))


def _estimate_chars(chars: int) -> int:
    if chars == 0:
        return 0
    return (chars + APPROXIMATE_CHARS_PER_TOKEN - 1) // APPROXIMATE_CHARS_PER_TOKEN


def estimate_messages_tokens(messages: Iterable[AgentMessage]) -> int:
    """不引入供应商 tokenizer，按序列化字符数估算 token。"""

    chars = sum(
        len(message.model_dump_json(by_alias=True, exclude_none=True))
        for message in messages
    )
    return _estimate_chars(chars)
