"""子 Agent 的工具策略与构造边界。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from .subagent import get_sub_agent_config
from .tooling import ToolEnvironment, ToolRegistry
from .tooling.selection import ToolSelectionPolicy, select_tools

if TYPE_CHECKING:
    from .agent import Agent


class SubagentFactoryHost(Protocol):
    """提供子 Agent 构造所需的最小父运行时能力。"""

    tool_registry: ToolRegistry
    tool_environment: ToolEnvironment

    def _child_api_kwargs(self) -> dict[str, Any]: ...

    def _child_permission_mode(self) -> str: ...


class SubagentFactory:
    """为父 Agent 创建受限工具与共享环境的子 Agent。"""

    def __init__(self, host: SubagentFactoryHost) -> None:
        self._host = host

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
                exclude_names=frozenset({"schedule_wakeup"}),
            )
        else:
            tool_policy = ToolSelectionPolicy(
                exclude_names=frozenset({"agent", "schedule_wakeup"}),
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

        return Agent(
            **self._host._child_api_kwargs(),
            custom_system_prompt=system_prompt,
            tool_registry=select_tools(self._host.tool_registry, tool_policy),
            tool_environment=self._host.tool_environment.child_view(),
            is_sub_agent=True,
            permission_mode=self._host._child_permission_mode(),
        )
