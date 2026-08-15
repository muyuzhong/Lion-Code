"""权限模式与确认缓存的唯一状态所有权。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

PermissionMode = Literal[
    "default",
    "acceptEdits",
    "bypassPermissions",
    "dontAsk",
]


class PermissionView(Protocol):
    """向权限消费者暴露实时只读状态。"""

    @property
    def mode(self) -> PermissionMode: ...

    def is_confirmed(self, value: str) -> bool: ...


class PermissionConfirmationSink(Protocol):
    """只允许记录已确认值的窄命令端口。"""

    def confirm(self, value: str) -> None: ...


@dataclass(slots=True)
class PermissionState:
    """由 ``PermissionController`` 独占写入的权限状态。"""

    mode: PermissionMode
    confirmed_values: set[str] = field(default_factory=set)


class PermissionController:
    """拥有权限模式与确认缓存，并提供读写分离的命令。"""

    def __init__(self, state: PermissionState) -> None:
        self._state = state

    @property
    def mode(self) -> PermissionMode:
        return self._state.mode

    def set_mode(self, mode: PermissionMode) -> None:
        self._state.mode = mode

    def is_confirmed(self, value: str) -> bool:
        return value in self._state.confirmed_values

    def confirm(self, value: str) -> None:
        self._state.confirmed_values.add(value)
