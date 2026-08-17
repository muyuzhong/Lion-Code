"""Lion Code：一个轻量级编码 Agent。"""

from .meta_agent import MetaAgent, build_coding_agent, build_meta_agent
from .supervisor import (
    Goal,
    JsonCheckpointStore,
    RetryPolicy,
    Supervisor,
    SupervisorResult,
    SupervisorState,
)

__version__ = "1.0.0"

__all__ = [
    "Goal",
    "JsonCheckpointStore",
    "MetaAgent",
    "RetryPolicy",
    "Supervisor",
    "SupervisorResult",
    "SupervisorState",
    "build_coding_agent",
    "build_meta_agent",
]
