"""Terminal title 文本清理工具(vendored 自 tau_coding/terminal_title.py 的子集)。

仅保留 ``sanitize_terminal_title``:terminal_notification 在写 OSC 序列前用它
剥离控制字符并截断长度。Tau 的 ``TerminalTitleController`` 及其标题构建/写入
逻辑零引用,已随零引用清理移除。
"""

from __future__ import annotations

import re

MAX_TERMINAL_TITLE_LENGTH = 120
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def sanitize_terminal_title(
    value: str | None,
    *,
    max_length: int = MAX_TERMINAL_TITLE_LENGTH,
) -> str:
    """Strip OSC-breaking control bytes and cap terminal-title text."""
    if value is None:
        return ""
    sanitized = _CONTROL_CHARS_RE.sub("", value).strip()
    if len(sanitized) <= max_length:
        return sanitized
    if max_length <= 1:
        return sanitized[:max_length]
    return sanitized[: max_length - 1].rstrip() + "…"
