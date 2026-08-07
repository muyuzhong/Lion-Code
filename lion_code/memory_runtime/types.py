"""Memory Overlay 的值对象与预算策略。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from lion_code.core.messages import AgentMessage
from lion_code.core.provider import ModelProvider


@dataclass(frozen=True, slots=True)
class MemoryOverlay:
    """一条只进入 Provider 投影、不进入 durable history 的 Memory。"""

    path: str
    content: str
    byte_size: int
    source: Literal["project", "session", "auto"] = "auto"
    required: bool = False


@dataclass(frozen=True, slots=True)
class MemoryInjectionReport:
    """记录一次投影实际注入与跳过的 Memory。"""

    injected_paths: tuple[str, ...] = ()
    injected_bytes: int = 0
    skipped_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryContextPolicy:
    """限制 Auto Memory 的活跃数量及单次、单会话字节预算。"""

    max_active_memories: int = 8
    max_injection_bytes: int = 24_000
    max_session_bytes: int = 60 * 1024


class ReadOnlyMessageSource(Protocol):
    """只读 Core Runtime 视图：只暴露消息快照和 Provider，不暴露 mutation 方法。

    Memory 层通过此 Protocol 访问 Core 状态，在类型层面无法调用
    ``clear_queues``、``follow_up``、``replace_messages`` 等 Harness 方法。
    """

    @property
    def messages(self) -> tuple[AgentMessage, ...]: ...

    @property
    def provider(self) -> ModelProvider: ...
