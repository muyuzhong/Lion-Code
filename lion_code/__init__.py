"""Lion Code 的 Profile、MetaAgent、Capability 与 Supervisor 公共 API。"""

from .capabilities import CapabilitySpec
from .composition import (
    AgentConfig,
    AgentDependencies,
    CodingProfile,
    FullProfile,
    MinimalProfile,
    Profile,
)
from .meta_agent import (
    MetaAgent,
    build_coding_agent,
    build_meta_agent,
    build_profile_agent,
)
from .supervisor import (
    AgentFactory,
    AgentPort,
    AsyncioScheduler,
    CheckpointError,
    CheckpointStore,
    Goal,
    JsonCheckpointStore,
    Phase,
    PublicAgentEventListener,
    PublicAgentResult,
    RetryPolicy,
    Scheduler,
    Status,
    Supervisor,
    SupervisorResult,
    SupervisorState,
    VolatileCheckpointStore,
)

__version__ = "1.0.0"

__all__ = [
    "AgentConfig",
    "AgentDependencies",
    "AgentFactory",
    "AgentPort",
    "AsyncioScheduler",
    "CapabilitySpec",
    "CheckpointError",
    "CheckpointStore",
    "CodingProfile",
    "FullProfile",
    "Goal",
    "JsonCheckpointStore",
    "MetaAgent",
    "MinimalProfile",
    "Phase",
    "Profile",
    "PublicAgentEventListener",
    "PublicAgentResult",
    "RetryPolicy",
    "Scheduler",
    "Status",
    "Supervisor",
    "SupervisorResult",
    "SupervisorState",
    "VolatileCheckpointStore",
    "build_coding_agent",
    "build_meta_agent",
    "build_profile_agent",
]
