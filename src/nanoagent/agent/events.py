"""NanoAgent agent 层对外发出的事件模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from nanoagent.agent.messages import AgentMessage
from nanoagent.agent.tools import AgentToolResult, ToolCall
from nanoagent.agent.types import JSONValue


class AgentStartEvent(BaseModel):
    """一次 agent run 开始。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["agent_start"] = "agent_start"


class AgentEndEvent(BaseModel):
    """一次 agent run 结束。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["agent_end"] = "agent_end"


class TurnStartEvent(BaseModel):
    """一个模型交互回合开始。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["turn_start"] = "turn_start"
    turn: int


class TurnEndEvent(BaseModel):
    """一个模型交互回合结束。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["turn_end"] = "turn_end"
    turn: int


class RetryEvent(BaseModel):
    """发生可恢复错误后安排重试。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["retry"] = "retry"
    attempt: int
    max_attempts: int
    delay_seconds: float
    message: str
    data: dict[str, JSONValue] | None = None


class QueueUpdateEvent(BaseModel):
    """转向消息或后续消息队列发生变化。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["queue_update"] = "queue_update"
    steering: tuple[str, ...] = ()
    follow_up: tuple[str, ...] = ()


class MessageStartEvent(BaseModel):
    """一条对话消息开始产生。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["message_start"] = "message_start"
    message_role: Literal["user", "assistant", "tool"] = "assistant"


class MessageDeltaEvent(BaseModel):
    """当前助手消息产生一段文本增量。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["message_delta"] = "message_delta"
    delta: str


class ThinkingDeltaEvent(BaseModel):
    """模型 reasoning/thinking 产生一段增量。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["thinking_delta"] = "thinking_delta"
    delta: str


class MessageEndEvent(BaseModel):
    """一条对话消息已经完整产生。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["message_end"] = "message_end"
    message: AgentMessage


class ToolExecutionStartEvent(BaseModel):
    """一个工具调用开始执行。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["tool_execution_start"] = "tool_execution_start"
    tool_call: ToolCall


class ToolExecutionUpdateEvent(BaseModel):
    """工具执行过程中产生中间状态更新。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["tool_execution_update"] = "tool_execution_update"
    tool_call_id: str
    message: str
    data: dict[str, JSONValue] | None = None


class ToolExecutionEndEvent(BaseModel):
    """一个工具调用执行结束。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["tool_execution_end"] = "tool_execution_end"
    result: AgentToolResult


class ErrorEvent(BaseModel):
    """agent 层报告的错误事件。"""

    model_config = ConfigDict(extra="forbid")

    type: Literal["error"] = "error"
    message: str
    recoverable: bool = False
    data: dict[str, JSONValue] | None = None


type AgentEvent = (
    AgentStartEvent
    | AgentEndEvent
    | TurnStartEvent
    | TurnEndEvent
    | QueueUpdateEvent
    | RetryEvent
    | MessageStartEvent
    | MessageDeltaEvent
    | ThinkingDeltaEvent
    | MessageEndEvent
    | ToolExecutionStartEvent
    | ToolExecutionUpdateEvent
    | ToolExecutionEndEvent
    | ErrorEvent
)
