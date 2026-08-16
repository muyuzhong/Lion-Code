"""Agent object graph 的 Composition Root。"""

from .agent_builder import AgentComposition, build_agent_composition
from .config import AgentConfig, AgentDependencies
from .profiles import (
    NEUTRAL_SYSTEM_PROMPT,
    CodingProfile,
    FullProfile,
    MinimalProfile,
    ProductFacadeKind,
    Profile,
    SkillComposition,
)

__all__ = [
    "NEUTRAL_SYSTEM_PROMPT",
    "AgentComposition",
    "AgentConfig",
    "AgentDependencies",
    "CodingProfile",
    "FullProfile",
    "MinimalProfile",
    "ProductFacadeKind",
    "Profile",
    "SkillComposition",
    "build_agent_composition",
]
