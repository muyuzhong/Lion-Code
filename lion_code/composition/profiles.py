"""不可变产品组合 Profile（Composition Preset）：只表达 WHAT TO BUILD。

Profile 只承载组合选择：内置 Capability 形态、调用方 tools、system prompt
与第三方 extension_specs。运行策略（AgentConfig）与具体实现绑定
（RuntimeBindings）不进入 Profile，三者在 Composition Root 汇合。
具体 Feature 名与构造 branch 只存在于 Composition Root。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..capabilities.types import CapabilitySpec
    from ..tooling.types import LionTool

NEUTRAL_SYSTEM_PROMPT = "You are a helpful assistant."


def _normalize_blank_prompt(profile) -> None:
    """空串 prompt 等价未提供：避免空串静默关闭动态上下文。"""
    if profile.system_prompt == "":
        object.__setattr__(profile, "system_prompt", None)


@dataclass(frozen=True, slots=True)
class MinimalProfile:
    """零内置 Capability 的最小产品：只注册调用方 tools 与第三方扩展。"""

    tools: tuple[LionTool, ...] = ()
    system_prompt: str | None = None
    extension_specs: tuple[CapabilitySpec, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "tools", tuple(self.tools))
        object.__setattr__(self, "extension_specs", tuple(self.extension_specs))
        _normalize_blank_prompt(self)


@dataclass(frozen=True, slots=True)
class CodingProfile:
    """Coding 产品形态：内置 Coding 工具套件、安全策略与第三方扩展。"""

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

    第三方扩展以 immutable ``CapabilitySpec`` values 组合，与内置形态正交。
    """

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
