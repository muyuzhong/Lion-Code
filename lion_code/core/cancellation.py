"""Core 共享的运行取消状态。"""

from __future__ import annotations

from typing import Protocol


class CancellationView(Protocol):
    """只读取消视图；Provider 与 Tool 只能观察当前运行状态。"""

    @property
    def cancelled(self) -> bool: ...

    def is_cancelled(self) -> bool: ...


class CancellationToken:
    """可复用的取消令牌；生命周期 Owner 负责 cancel/reset。"""

    __slots__ = ("_cancelled",)

    def __init__(self) -> None:
        self._cancelled = False

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True

    def reset(self) -> None:
        self._cancelled = False


__all__ = ["CancellationToken", "CancellationView"]
