"""派生 Provider 消息投影所需的非破坏性辅助函数。"""

from __future__ import annotations

from collections.abc import Iterable

from lion_code.core.messages import AgentMessage, TextContent, ToolResultMessage


def project_messages(messages: Iterable[AgentMessage]) -> list[AgentMessage]:
    """返回深拷贝，确保活跃上下文改写不会污染 durable history。"""

    return [message.model_copy(deep=True) for message in messages]


def replace_tool_result_text(message: ToolResultMessage, text: str) -> None:
    """替换文本块，同时按原顺序保留非文本结果内容。"""

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
