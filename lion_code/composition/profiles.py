"""不可变产品组合 Profile：组合选择的单一来源。

Profile 只承载组合数据（Provider/依赖、tools、permission strategy、prompt、
backend、facade 选择），不拥有 lifecycle、不解析服务、不暴露 runtime lookup。
具体 Feature 名与构造 branch 只存在于 Composition Root。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from ..tooling.execution import (
    CommandExecutionBackend,
    LocalCommandExecutionBackend,
)

if TYPE_CHECKING:
    from ..capabilities.types import CapabilitySpec
    from ..tooling.permission import ToolPermissionStrategy
    from ..tooling.types import LionTool
    from .config import AgentConfig, AgentDependencies

NEUTRAL_SYSTEM_PROMPT = "You are a helpful assistant."


class ProductFacadeKind(Enum):
    """Profile 固定选择的 facade 类型；只描述外观，不编码 Feature。"""

    META = "meta"
    FULL = "full"


@dataclass(frozen=True, slots=True)
class SkillComposition:
    """Coding 可选 Skill 组合的存在值（presence value，非 bool 开关）。"""


def _normalize_blank_prompt(profile) -> None:
    """空串 prompt 等价未提供：避免空串静默关闭动态上下文。"""
    if profile.system_prompt == "":
        object.__setattr__(profile, "system_prompt", None)


@dataclass(frozen=True, slots=True)
class MinimalProfile:
    """零内置 Capability 的最小产品：只注册调用方 tools 与 Meta facade。"""

    config: AgentConfig
    dependencies: AgentDependencies
    tools: tuple[LionTool, ...] = ()
    permission_strategy: ToolPermissionStrategy | None = None
    system_prompt: str | None = None
    facade: ProductFacadeKind = field(default=ProductFacadeKind.META, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "tools", tuple(self.tools))
        _normalize_blank_prompt(self)


@dataclass(frozen=True, slots=True)
class CodingProfile:
    """Coding 产品形态：backend 绑定的 Coding 工具套件与可选 Skill。

    Profile 类型固定选择 Coding tool suite；是否组合 Skill 由可选
    ``skill`` 值表达，不使用 feature bool。
    """

    config: AgentConfig
    dependencies: AgentDependencies
    command_backend: CommandExecutionBackend = field(
        default_factory=LocalCommandExecutionBackend,
    )
    permission_strategy: ToolPermissionStrategy | None = None
    extra_tools: tuple[LionTool, ...] = ()
    system_prompt: str | None = None
    skill: SkillComposition | None = None
    facade: ProductFacadeKind = field(default=ProductFacadeKind.META, init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "extra_tools", tuple(self.extra_tools))
        _normalize_blank_prompt(self)


@dataclass(frozen=True, slots=True)
class FullProfile:
    """Full 产品：Coding 形态 + Memory/Plan/SubAgent/默认 Skill 与完整 facade。

    第三方扩展以 immutable ``CapabilitySpec`` values 组合，不进入 dependencies。
    """

    config: AgentConfig
    dependencies: AgentDependencies
    command_backend: CommandExecutionBackend = field(
        default_factory=LocalCommandExecutionBackend,
    )
    permission_strategy: ToolPermissionStrategy | None = None
    extra_tools: tuple[LionTool, ...] = ()
    system_prompt: str | None = None
    extension_specs: tuple[CapabilitySpec, ...] = ()
    facade: ProductFacadeKind = field(default=ProductFacadeKind.FULL, init=False)

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
    "ProductFacadeKind",
    "Profile",
    "SkillComposition",
]
