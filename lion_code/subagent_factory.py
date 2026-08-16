"""子 Agent 的工具策略与构造边界。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .subagent import get_sub_agent_config
from .tooling import ToolRegistry
from .tooling.selection import ToolSelectionPolicy, select_tools

if TYPE_CHECKING:
    from .agent import Agent


@dataclass(frozen=True, slots=True)
class ChildAgentConfig:
    """构造一个子 Agent 所需的 Provider 与界面配置快照。"""

    model: str
    api_key: str
    api_base: str | None = None
    anthropic_base_url: str | None = None
    terminal_output: bool = True


class SubagentFactory:
    """为父 Agent 创建受限工具视图的子 Agent。"""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        child_config: Callable[[], ChildAgentConfig],
    ) -> None:
        self._registry = registry
        self._child_config = child_config

    def create_for_agent_type(self, agent_type: str) -> Agent:
        """按内置或自定义 Agent 类型创建子实例。"""

        config = get_sub_agent_config(agent_type)
        return self._create(
            system_prompt=config.system_prompt,
            tool_policy=config.tool_policy,
        )

    def create_for_skill(
        self,
        *,
        system_prompt: str,
        allowed_tools: list[str] | None,
    ) -> Agent:
        """按 Skill 声明的工具范围创建 fork 子实例。"""

        if allowed_tools:
            tool_policy = ToolSelectionPolicy(
                allowed_names=frozenset(allowed_tools),
            )
        else:
            tool_policy = ToolSelectionPolicy(
                exclude_names=frozenset({"agent"}),
            )
        return self._create(system_prompt=system_prompt, tool_policy=tool_policy)

    def _create(
        self,
        *,
        system_prompt: str,
        tool_policy: ToolSelectionPolicy,
    ) -> Agent:
        """在真正构造时才导入 Agent，避免模块级循环依赖。"""

        from .agent import Agent

        config = self._child_config()
        return Agent(
            model=config.model,
            api_key=config.api_key,
            api_base=config.api_base,
            anthropic_base_url=config.anthropic_base_url,
            terminal_output=config.terminal_output,
            custom_system_prompt=system_prompt,
            tool_registry=select_tools(self._registry, tool_policy),
            is_sub_agent=True,
            permission_mode="bypassPermissions",
        )
