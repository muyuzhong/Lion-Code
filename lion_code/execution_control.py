"""单次 Agent 运行的取消命令 Owner。"""

from __future__ import annotations

from .core.cancellation import CancellationToken, CancellationView


class ExecutionControl:
    """持有唯一取消令牌，并提供运行开始与取消命令。"""

    def __init__(self) -> None:
        self._token = CancellationToken()

    @property
    def cancelled(self) -> bool:
        return self._token.cancelled

    @property
    def cancellation(self) -> CancellationView:
        return self._token

    def begin(self) -> None:
        self._token.reset()

    def cancel(self) -> None:
        self._token.cancel()
