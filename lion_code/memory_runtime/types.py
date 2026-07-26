"""Memory Overlay 的值对象与预算策略。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MemoryOverlay:
    """一条只进入 Provider 投影、不进入 durable history 的 Memory。"""

    path: str
    content: str
    byte_size: int


@dataclass(frozen=True, slots=True)
class MemoryInjectionReport:
    """记录一次投影实际注入与跳过的 Memory。"""

    injected_paths: tuple[str, ...] = ()
    injected_bytes: int = 0
    skipped_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class MemoryContextPolicy:
    """限制活跃 Memory 数量及单次、单会话字节预算。"""

    max_active_memories: int = 8
    max_injection_bytes: int = 24_000
    max_session_bytes: int = 60 * 1024
