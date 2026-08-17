"""Application-owned coding-session facade and event contracts.

``LionCodingSession`` consumes the small protocols from ``ports``.  Agent and
runtime implementations provide those protocols structurally; this package
does not import their implementation details.
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
from .ports import (
    CodingSessionBackend,
    ControlPort,
    ConversationPort,
    QueueSnapshot,
    SessionPort,
    SettingsPort,
    UsagePort,
)
from .session import LionCodingSession, StreamingBehavior

__all__ = [
    "AgentSettledEvent",
    "AutoRetryEndEvent",
    "AutoRetryStartEvent",
    "CodingSessionBackend",
    "CompactionEndEvent",
    "CompactionReason",
    "CompactionStartEvent",
    "ControlPort",
    "ConversationPort",
    "LionCodingSession",
    "LionSessionEvent",
    "ProviderChangedEvent",
    "QueueSnapshot",
    "QueueUpdateEvent",
    "SessionAgentEndEvent",
    "SessionChangedEvent",
    "SessionOwnEvent",
    "SessionPort",
    "SettingsPort",
    "StreamingBehavior",
    "ThinkingLevelChangedEvent",
    "UsagePort",
]
