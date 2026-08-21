"""全部工具输出进入模型上下文前的统一 redact 窄腰（post 链首位）。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Literal

from .context import ToolContext
from .middleware import NextCall
from .secret_provider import SecretStore
from .types import JSONValue, LionTool, ToolResult

REDACTED = "***"

# 行内切分符：空白、引号与标签尖括号。不放 / 与 = —— 两者都在
# base64 字母表/填充里，切开会破坏 b64 变体的整串指纹比对
_SPLIT = re.compile(r"""([\s"'`<>]+)""")

# 值两端常见包裹字符
_EDGE_CHARS = "\"'`()[]{},;:<>|"


def _value_candidates(chunk: str) -> list[str]:
    """从一段文本派生可能的取值形态：原文、去包裹、KEY=VALUE 的值部。"""
    candidates = [chunk]
    stripped = chunk.strip(_EDGE_CHARS)
    if stripped and stripped != chunk:
        candidates.append(stripped)
    if "=" in chunk:
        value = chunk.rsplit("=", 1)[1].strip(_EDGE_CHARS)
        if value:
            candidates.append(value)
    return candidates


def sanitize_text(text: str, store: SecretStore) -> tuple[str, int]:
    """指纹比对 redact；供输出窄腰与审计参数序列化共用。"""
    if not store.fingerprints():
        return text, 0
    hits = 0
    lines = text.split("\n")
    for index, line in enumerate(lines):
        replaced, count = _sanitize_line(line, store)
        hits += count
        lines[index] = replaced
    return "\n".join(lines), hits


def _sanitize_line(line: str, store: SecretStore) -> tuple[str, int]:
    # 行粒度先比对：覆盖独占一行的裸值与 KEY="含空格值" 两种形态
    for candidate in _value_candidates(line):
        if store.matches(candidate):
            return line.replace(candidate, REDACTED), 1
    parts = _SPLIT.split(line)
    hits = 0
    for index in range(0, len(parts), 2):
        for candidate in _value_candidates(parts[index]):
            if store.matches(candidate):
                parts[index] = parts[index].replace(candidate, REDACTED)
                hits += 1
                break
    return "".join(parts), hits


class OutputSanitizerMiddleware:
    """对工具结果内容做指纹比对 redact；计数写入 details 供审计消费。"""

    phase: Literal["post"] = "post"

    def __init__(self, store: SecretStore) -> None:
        self.store = store

    async def handle(
        self,
        *,
        tool: LionTool,
        context: ToolContext,
        tool_call_id: str,
        arguments: Mapping[str, JSONValue],
        call_next: NextCall,
    ) -> ToolResult:
        del tool, context, tool_call_id, arguments
        result = await call_next()
        sanitized, hits = sanitize_text(result.content, self.store)
        if hits:
            result.content = sanitized
            result.details = {**result.details, "sanitizer_hits": hits}
        return result
