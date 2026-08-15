"""Agent object graph 的 Composition Root。"""

from .agent_builder import (
    PRODUCT_CAPABILITIES,
    AgentComposition,
    build_agent_composition,
)
from .config import AgentConfig, AgentDependencies

__all__ = [
    "PRODUCT_CAPABILITIES",
    "AgentComposition",
    "AgentConfig",
    "AgentDependencies",
    "build_agent_composition",
]
