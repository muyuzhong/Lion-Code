"""Agent 的用户可见运行配置（HOW IT RUNS）。

只描述值型运行策略：model、endpoint、权限模式、thinking、预算与轮次等。
不保存 mutable runtime object——具体实现绑定由 RuntimeBindings 承载。
prompt、tools 等组合选择由 Profile 承载，不在本配置中。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..permission_state import PermissionMode


@dataclass(frozen=True, slots=True)
class AgentConfig:
    """只描述用户可见的 Agent 运行配置，不保存运行时对象。"""

    model: str = "claude-opus-4-6"
    api_base: str | None = None
    anthropic_base_url: str | None = None
    api_key: str | None = None
    permission_mode: PermissionMode = "default"
    thinking: bool = False
    max_cost_usd: float | None = None
    max_turns: int | None = None
    is_sub_agent: bool = False
    terminal_output: bool = True
