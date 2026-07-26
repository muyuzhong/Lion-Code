"""应用会话层事件模型。

Core 的 ``AgentEvent`` 只描述单次 Agent 循环;应用层在其上补充「会话级」
语义:一轮彻底归位(Settled)、队列变化、压缩、自动重试、会话/供应商切换。
事件集对齐 Tau 0.3.3 中实际被 emit 的集合(见 docs/tui-migration-audit.md §9),
并做 Lion 增补。

关键契约:

- ``AgentEndEvent`` 不代表 UI 可以归位——AgentEnd 之后可能还有溢出压缩、
  自动重试、steering 续跑;前端必须以 ``AgentSettledEvent`` 为空闲信号。
- 溢出重试路径的事件次序:``SessionAgentEnd → CompactionStart(overflow) →
  CompactionEnd → AutoRetryStart → …续跑事件… → AutoRetryEnd → AgentSettled``。
- 底层 ``AgentEvent``(MessageUpdate/ToolExecution* 等)原样透传,
  唯 ``AgentEndEvent`` 被包装为 ``SessionAgentEndEvent``。
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from lion_code.core.events import AgentEvent
from lion_code.core.messages import AgentMessage, WireModel

type CompactionReason = Literal["manual", "threshold", "overflow"]
type SessionChangeReason = Literal["new", "resume", "clear"]


class SessionAgentEndEvent(WireModel):
    """包装底层 AgentEnd:一次 Agent 循环结束,但本轮可能尚未归位。"""

    type: Literal["session_agent_end"] = "session_agent_end"
    messages: list[AgentMessage] = Field(default_factory=list)
    will_retry: bool = False


class AgentSettledEvent(WireModel):
    """一轮彻底结束(压缩/重试/续跑都已完成),UI 可以归位。"""

    type: Literal["agent_settled"] = "agent_settled"


class QueueUpdateEvent(WireModel):
    """运行中入队的 steering / follow-up 文本快照。"""

    type: Literal["queue_update"] = "queue_update"
    steering: tuple[str, ...] = ()
    follow_up: tuple[str, ...] = Field(default=(), serialization_alias="followUp")


class CompactionStartEvent(WireModel):
    type: Literal["compaction_start"] = "compaction_start"
    reason: CompactionReason


class CompactionEndEvent(WireModel):
    type: Literal["compaction_end"] = "compaction_end"
    reason: CompactionReason
    aborted: bool = False
    will_retry: bool = False
    error_message: str | None = Field(
        default=None, serialization_alias="errorMessage"
    )


class AutoRetryStartEvent(WireModel):
    type: Literal["auto_retry_start"] = "auto_retry_start"
    attempt: int
    max_attempts: int = Field(serialization_alias="maxAttempts")
    delay_ms: int = Field(serialization_alias="delayMs")
    error_message: str = Field(serialization_alias="errorMessage")


class AutoRetryEndEvent(WireModel):
    type: Literal["auto_retry_end"] = "auto_retry_end"
    success: bool
    attempt: int
    final_error: str | None = Field(default=None, serialization_alias="finalError")


class SessionChangedEvent(WireModel):
    """活动会话被替换(新建/恢复/清空)。"""

    type: Literal["session_changed"] = "session_changed"
    session_id: str = Field(serialization_alias="sessionId")
    reason: SessionChangeReason


class ProviderChangedEvent(WireModel):
    """供应商或模型切换生效。"""

    type: Literal["provider_changed"] = "provider_changed"
    provider_name: str = Field(serialization_alias="providerName")
    model: str


class ThinkingLevelChangedEvent(WireModel):
    type: Literal["thinking_level_changed"] = "thinking_level_changed"
    level: str


type SessionOwnEvent = Annotated[
    SessionAgentEndEvent
    | AgentSettledEvent
    | QueueUpdateEvent
    | CompactionStartEvent
    | CompactionEndEvent
    | AutoRetryStartEvent
    | AutoRetryEndEvent
    | SessionChangedEvent
    | ProviderChangedEvent
    | ThinkingLevelChangedEvent,
    Field(discriminator="type"),
]

type LionSessionEvent = AgentEvent | SessionOwnEvent
