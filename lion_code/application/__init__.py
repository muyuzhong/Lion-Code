"""Lion 应用会话层。

向前端(TUI/CLI)暴露一个稳定的会话门面 ``LionCodingSession`` 与应用级
事件模型 ``LionSessionEvent``。本层只做组合:内部复用 LionAgentRuntime、
ToolRuntime、SessionRecorder/Repository、ContextManager、MemoryCoordinator,
不实现第二套 Agent Loop,也不接触供应商消息格式。

依赖方向:TUI → application → agent_runtime → core;禁止反向。
"""

from .events import (
    AgentSettledEvent,
    AutoRetryEndEvent,
    AutoRetryStartEvent,
    CompactionEndEvent,
    CompactionReason,
    CompactionStartEvent,
    LionSessionEvent,
    ProviderChangedEvent,
    QueueUpdateEvent,
    SessionAgentEndEvent,
    SessionChangedEvent,
    SessionOwnEvent,
    ThinkingLevelChangedEvent,
)
from .session import LionCodingSession, StreamingBehavior

__all__ = [
    "AgentSettledEvent",
    "AutoRetryEndEvent",
    "AutoRetryStartEvent",
    "CompactionEndEvent",
    "CompactionReason",
    "CompactionStartEvent",
    "LionCodingSession",
    "LionSessionEvent",
    "ProviderChangedEvent",
    "QueueUpdateEvent",
    "SessionAgentEndEvent",
    "SessionChangedEvent",
    "SessionOwnEvent",
    "StreamingBehavior",
    "ThinkingLevelChangedEvent",
]
