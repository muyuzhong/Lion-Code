"""Generic Capability SPI：extension slot protocols 与 Registry/Runtime。

本模块不知道任何具体 feature（plan/skill/subagent）；feature-specific
实现位于各自的 feature package，构造分支只存在于 Composition Root。
"""

from __future__ import annotations

from .registry import CapabilityRegistry, DuplicateCapabilityError
from .runtime import CapabilityLifecycle, CapabilityRuntime
from .types import (
    AsyncCloseable,
    CapabilitySpec,
    ContextLayer,
    PromptLayer,
    QueryContextLayer,
    SessionParticipant,
    ToolSource,
)

__all__ = [
    "AsyncCloseable",
    "CapabilityLifecycle",
    "CapabilityRegistry",
    "CapabilityRuntime",
    "CapabilitySpec",
    "ContextLayer",
    "DuplicateCapabilityError",
    "PromptLayer",
    "QueryContextLayer",
    "SessionParticipant",
    "ToolSource",
]
