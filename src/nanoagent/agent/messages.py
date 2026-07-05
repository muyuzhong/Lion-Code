"""与 provider 无关的对话记录消息模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nanoagent.agent.tools import ToolCall
from nanoagent.agent.types import JSONValue


class UserMessage(BaseModel):
    """用户输入消息。"""

    model_config = ConfigDict(extra="forbid")

    role: Literal["user"] = "user"
    content: str


class AssistantMessage(BaseModel):
    """助手输出消息，可携带需要执行的工具调用。"""

    model_config = ConfigDict(extra="forbid")

    role: Literal["assistant"] = "assistant"
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)


class ToolResultMessage(BaseModel):
    """工具调用结果消息，用于把工具返回值写回对话记录。"""

    model_config = ConfigDict(extra="forbid")

    role: Literal["tool"] = "tool"
    tool_call_id: str
    name: str
    content: str
    ok: bool = True
    data: dict[str, JSONValue] | None = None
    details: dict[str, JSONValue] | None = None
    error: str | None = None


type AgentMessage = UserMessage | AssistantMessage | ToolResultMessage
