"""SubAgent feature：agent 类型定义、工厂、执行运行时与 Capability 贡献。"""

from .capability import create_subagent_capability
from .factory import ChildAgentConfig, SubagentFactory
from .runtime import SubagentExecutor, SubagentStatusCallback
from .types import get_sub_agent_config

__all__ = [
    "ChildAgentConfig",
    "SubagentExecutor",
    "SubagentFactory",
    "SubagentStatusCallback",
    "create_subagent_capability",
    "get_sub_agent_config",
]
