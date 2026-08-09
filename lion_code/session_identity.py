"""活动 Session identity 的单一状态 Owner 与只读视图。"""

from __future__ import annotations

from typing import Protocol


class SessionView(Protocol):
    """当前活动会话的只读标识。"""

    @property
    def id(self) -> str: ...

    @property
    def started_at(self) -> str: ...


class SessionIdentityState:
    """保存活动会话标识；构造完成后仅由 SessionLifecycle 重置。"""

    __slots__ = ("_id", "_started_at")

    def __init__(self, id: str, started_at: str) -> None:
        self._id = id
        self._started_at = started_at

    @property
    def id(self) -> str:
        return self._id

    @property
    def started_at(self) -> str:
        return self._started_at

    def reset(self, id: str, started_at: str) -> None:
        self._id = id
        self._started_at = started_at
