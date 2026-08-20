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


def budget_text(text: str, budget: int) -> str:
    """在字符预算内对称保留文本首尾，并标记省略规模。"""

    if budget <= 0:
        return ""
    if len(text) <= budget:
        return text

    low = 0
    high = budget // 2
    best = ""
    while low <= high:
        keep = (low + high) // 2
        omitted = len(text) - keep * 2
        marker = f"\n\n[... budgeted: {omitted} chars truncated ...]\n\n"
        candidate = text[:keep] + marker + text[-keep:] if keep else marker
        if len(candidate) <= budget:
            best = candidate
            low = keep + 1
        else:
            high = keep - 1
    return best[:budget]
