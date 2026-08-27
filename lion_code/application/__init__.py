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
    QueueUpdateEvent,
    SessionAgentEndEvent,
    SessionOwnEvent,
)
from .ports import (
    CodingSessionBackend,
    ControlPort,
    ConversationPort,
    EgressConfigurationPort,
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
    "EgressConfigurationPort",
    "LionCodingSession",
    "LionSessionEvent",
    "QueueSnapshot",
    "QueueUpdateEvent",
    "SessionAgentEndEvent",
    "SessionOwnEvent",
    "SessionPort",
    "SettingsPort",
    "StreamingBehavior",
    "UsagePort",
]
