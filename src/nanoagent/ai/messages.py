from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Union

from nanoagent.ai.stop_reason import StopReason
from nanoagent.ai.types import JSONValue
from nanoagent.utils import new_id


# ---- 内容块：provider 和 agent 之间共享的 wire 级消息片段 ----
@dataclass
class TextContent:
    """普通文本内容。"""

    text: str
    type: Literal["text"] = "text"


@dataclass
class ThinkingContent:
    """模型 reasoning/thinking 内容；是否展示由上层决定。"""

    thinking: str
    type: Literal["thinking"] = "thinking"


@dataclass
class ImageContent:
    """用户输入中的图片内容，data 使用 base64 编码。"""

    data: str  # base64
    mime_type: str
    type: Literal["image"] = "image"


@dataclass
class ToolCall:
    """模型请求执行的工具调用。"""

    id: str
    name: str
    arguments: dict[str, JSONValue]
    type: Literal["toolCall"] = "toolCall"


AssistantContent = Union[TextContent, ThinkingContent, ToolCall]
UserContent = Union[TextContent, ImageContent]


@dataclass
class Usage:
    """provider 返回的 token 用量；缺失 total 时可由 input/output 推导。"""

    input: int = 0
    output: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        if self.total_tokens == 0 and (self.input or self.output):
            self.total_tokens = self.input + self.output


# ---- 消息：这是 provider 可见的 wire transcript，不包含应用层 custom message ----
@dataclass
class UserMessage:
    """用户侧 wire 消息。"""

    content: str | list[UserContent]
    role: Literal["user"] = "user"
    id: str = field(default_factory=lambda: new_id("msg"))


@dataclass
class AssistantMessage:
    """模型输出的 wire 消息，包含内容块、模型归属、用量和 provider 级停止原因。"""

    content: list[AssistantContent]
    model: str
    provider: str
    api: str
    usage: Usage
    stop_reason: StopReason
    error_message: str | None = None
    role: Literal["assistant"] = "assistant"
    id: str = field(default_factory=lambda: new_id("msg"))

    @classmethod
    def empty(cls, model: str, provider: str, api: str) -> AssistantMessage:
        """创建一个用于流式累积的空 assistant 消息。"""
        return cls(
            content=[],
            model=model,
            provider=provider,
            api=api,
            usage=Usage(),
            stop_reason=StopReason.STOP,
        )


@dataclass
class ToolResultMessage:
    """工具执行结果消息，会作为下一回合上下文的一部分传给模型。"""

    tool_call_id: str
    tool_name: str
    content: list[UserContent]
    is_error: bool = False
    data: dict[str, JSONValue] | None = None
    details: dict[str, JSONValue] | None = None
    error: str | None = None
    role: Literal["toolResult"] = "toolResult"
    id: str = field(default_factory=lambda: new_id("msg"))

    @property
    def ok(self) -> bool:
        return not self.is_error


Message = Union[UserMessage, AssistantMessage, ToolResultMessage]


@dataclass
class Context:
    """一次模型调用的完整上下文快照。"""

    system_prompt: list[str] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    tools: list[Any] = field(default_factory=list)  # list[Tool]; Any avoids a back-dep on tools.py

    def __post_init__(self) -> None:
        # 隔离列表结构，避免调用方后续修改原列表污染已构造的 Context。
        self.system_prompt = list(self.system_prompt)
        self.messages = list(self.messages)
        self.tools = list(self.tools)
