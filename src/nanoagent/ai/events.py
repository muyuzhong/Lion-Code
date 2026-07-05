from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

from nanoagent.ai.messages import AssistantMessage, ToolCall


@dataclass
class StreamStart:
    """一次 assistant 流开始。"""

    type: str = field(default="start", init=False)


@dataclass
class TextStart:
    """某个文本内容块开始。"""

    content_index: int
    type: str = field(default="text_start", init=False)


@dataclass
class TextDelta:
    """文本内容块的增量片段。"""

    content_index: int
    delta: str
    type: str = field(default="text_delta", init=False)


@dataclass
class TextEnd:
    """文本内容块结束，并给出最终文本。"""

    content_index: int
    text: str
    type: str = field(default="text_end", init=False)


@dataclass
class ThinkingStart:
    """thinking 内容块开始。"""

    content_index: int
    type: str = field(default="thinking_start", init=False)


@dataclass
class ThinkingDelta:
    """thinking 内容块的增量片段。"""

    content_index: int
    delta: str
    type: str = field(default="thinking_delta", init=False)


@dataclass
class ThinkingEnd:
    """thinking 内容块结束，并给出最终内容。"""

    content_index: int
    thinking: str
    type: str = field(default="thinking_end", init=False)


@dataclass
class ToolCallStart:
    """工具调用内容块开始。"""

    content_index: int
    type: str = field(default="toolcall_start", init=False)


@dataclass
class ToolCallDelta:
    """工具调用参数的原始增量片段。"""

    content_index: int
    delta: str
    type: str = field(default="toolcall_delta", init=False)


@dataclass
class ToolCallEnd:
    """工具调用内容块结束，并给出解析后的 ToolCall。"""

    content_index: int
    tool_call: ToolCall
    type: str = field(default="toolcall_end", init=False)


@dataclass
class StreamDone:
    """provider 正常结束，并给出最终 assistant 消息。"""

    message: AssistantMessage
    type: str = field(default="done", init=False)


@dataclass
class StreamError:
    """provider 出错结束，错误信息写入 message。"""

    message: AssistantMessage
    type: str = field(default="error", init=False)


AssistantMessageEvent = Union[
    StreamStart,
    TextStart,
    TextDelta,
    TextEnd,
    ThinkingStart,
    ThinkingDelta,
    ThinkingEnd,
    ToolCallStart,
    ToolCallDelta,
    ToolCallEnd,
    StreamDone,
    StreamError,
]
