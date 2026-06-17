from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Union

from nanoagent.ai import AssistantMessageEvent, ToolResultMessage
from nanoagent.agent.messages import AgentMessage
from nanoagent.agent.result import RunResult


@dataclass
class AgentStart:
    type: str = "agent_start"


@dataclass
class AgentEnd:
    messages: list[AgentMessage]
    result: RunResult
    type: str = "agent_end"


@dataclass
class TurnStart:
    type: str = "turn_start"


@dataclass
class TurnEnd:
    message: AgentMessage
    tool_results: list[ToolResultMessage] = field(default_factory=list)
    type: str = "turn_end"


@dataclass
class MessageStart:
    message: AgentMessage
    type: str = "message_start"


@dataclass
class MessageUpdate:
    message: AgentMessage
    assistant_event: AssistantMessageEvent
    type: str = "message_update"


@dataclass
class MessageEnd:
    message: AgentMessage
    type: str = "message_end"


@dataclass
class ToolExecutionStart:
    tool_call_id: str
    tool_name: str
    args: dict[str, Any]
    type: str = "tool_execution_start"


@dataclass
class ToolExecutionUpdate:
    tool_call_id: str
    tool_name: str
    partial_result: Any
    type: str = "tool_execution_update"


@dataclass
class ToolExecutionEnd:
    tool_call_id: str
    tool_name: str
    result: Any
    is_error: bool = False
    type: str = "tool_execution_end"


AgentEvent = Union[
    AgentStart,
    AgentEnd,
    TurnStart,
    TurnEnd,
    MessageStart,
    MessageUpdate,
    MessageEnd,
    ToolExecutionStart,
    ToolExecutionUpdate,
    ToolExecutionEnd,
]
