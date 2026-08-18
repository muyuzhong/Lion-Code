"""Pi-compatible events emitted by Lion's portable agent layer."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from lion_code.core.messages import AgentMessage, ToolResultMessage, WireModel
from lion_code.core.provider_events import AssistantMessageEvent
from lion_code.core.tools import AgentToolResult
from lion_code.core.types import JSONValue


class AgentStartEvent(WireModel):
    type: Literal["agent_start"] = "agent_start"


class AgentEndEvent(WireModel):
    type: Literal["agent_end"] = "agent_end"


class TurnStartEvent(WireModel):
    type: Literal["turn_start"] = "turn_start"


class TurnEndEvent(WireModel):
    type: Literal["turn_end"] = "turn_end"
    message: AgentMessage
    tool_results: list[ToolResultMessage] = Field(default_factory=list)


class MessageStartEvent(WireModel):
    type: Literal["message_start"] = "message_start"
    message: AgentMessage


class MessageUpdateEvent(WireModel):
    type: Literal["message_update"] = "message_update"
    message: AgentMessage
    assistant_message_event: AssistantMessageEvent = Field(
        serialization_alias="assistantMessageEvent"
    )


class MessageEndEvent(WireModel):
    type: Literal["message_end"] = "message_end"
    message: AgentMessage


class ToolExecutionStartEvent(WireModel):
    type: Literal["tool_execution_start"] = "tool_execution_start"
    tool_call_id: str
    tool_name: str
    args: dict[str, JSONValue] = Field(default_factory=dict)


class ToolExecutionUpdateEvent(WireModel):
    type: Literal["tool_execution_update"] = "tool_execution_update"
    tool_call_id: str
    tool_name: str
    args: dict[str, JSONValue] = Field(default_factory=dict)
    partial_result: AgentToolResult


class ToolExecutionEndEvent(WireModel):
    type: Literal["tool_execution_end"] = "tool_execution_end"
    tool_call_id: str
    tool_name: str
    result: AgentToolResult
    is_error: bool


class CompactionStartedEvent(WireModel):
    type: Literal["compaction_started"] = "compaction_started"
    reason: Literal["threshold", "overflow", "manual"] = "threshold"


class CompactionCompletedEvent(WireModel):
    type: Literal["compaction_completed"] = "compaction_completed"
    reason: Literal["threshold", "overflow", "manual"] = "threshold"
    aborted: bool = False


class TurnFailedEvent(WireModel):
    type: Literal["turn_failed"] = "turn_failed"
    message: AgentMessage


class CancelledEvent(WireModel):
    type: Literal["cancelled"] = "cancelled"
    message: AgentMessage | None = None


type AgentEvent = Annotated[
    AgentStartEvent
    | AgentEndEvent
    | TurnStartEvent
    | TurnEndEvent
    | MessageStartEvent
    | MessageUpdateEvent
    | MessageEndEvent
    | ToolExecutionStartEvent
    | ToolExecutionUpdateEvent
    | ToolExecutionEndEvent
    | CompactionStartedEvent
    | CompactionCompletedEvent
    | TurnFailedEvent
    | CancelledEvent,
    Field(discriminator="type"),
]
