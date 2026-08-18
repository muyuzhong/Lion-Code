"""不可变产品组合 Profile：组合选择的单一来源。

Profile 只承载组合数据（Provider/依赖、tools、prompt、backend），不拥有
lifecycle、不解析服务、不暴露 runtime lookup。
具体 Feature 名与构造 branch 只存在于 Composition Root。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..tooling.execution import (
    CommandExecutionBackend,
    LocalCommandExecutionBackend,
)

if TYPE_CHECKING:
    from ..capabilities.types import CapabilitySpec
    from ..tooling.types import LionTool
    from .config import AgentConfig, AgentDependencies

NEUTRAL_SYSTEM_PROMPT = "You are a helpful assistant."


def _normalize_blank_prompt(profile) -> None:
    """空串 prompt 等价未提供：避免空串静默关闭动态上下文。"""
    if profile.system_prompt == "":
        object.__setattr__(profile, "system_prompt", None)


@dataclass(frozen=True, slots=True)
class MinimalProfile:
    """零内置 Capability 的最小产品：只注册调用方 tools 与第三方扩展。"""

    config: AgentConfig
    dependencies: AgentDependencies
    tools: tuple[LionTool, ...] = ()
    system_prompt: str | None = None
    extension_specs: tuple[CapabilitySpec, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "tools", tuple(self.tools))
        object.__setattr__(self, "extension_specs", tuple(self.extension_specs))
        _normalize_blank_prompt(self)


@dataclass(frozen=True, slots=True)
class CodingProfile:
    """Coding 产品形态：backend 绑定的 Coding 工具套件、安全策略与第三方扩展。"""

    config: AgentConfig
    dependencies: AgentDependencies
    command_backend: CommandExecutionBackend = field(
        default_factory=LocalCommandExecutionBackend,
    )
    extra_tools: tuple[LionTool, ...] = ()
    system_prompt: str | None = None
    extension_specs: tuple[CapabilitySpec, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra_tools", tuple(self.extra_tools))
        object.__setattr__(self, "extension_specs", tuple(self.extension_specs))
        _normalize_blank_prompt(self)


@dataclass(frozen=True, slots=True)
class FullProfile:
    """Full 产品：Coding 形态 + Plan/SubAgent/默认 Skill。

    第三方扩展以 immutable ``CapabilitySpec`` values 组合，不进入 dependencies。
    """

    config: AgentConfig
    dependencies: AgentDependencies
    command_backend: CommandExecutionBackend = field(
        default_factory=LocalCommandExecutionBackend,
    )
    extra_tools: tuple[LionTool, ...] = ()
    system_prompt: str | None = None
    extension_specs: tuple[CapabilitySpec, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra_tools", tuple(self.extra_tools))
        object.__setattr__(self, "extension_specs", tuple(self.extension_specs))
        _normalize_blank_prompt(self)


Profile = MinimalProfile | CodingProfile | FullProfile

__all__ = [
    "NEUTRAL_SYSTEM_PROMPT",
    "CodingProfile",
    "FullProfile",
    "MinimalProfile",
    "Profile",
]
