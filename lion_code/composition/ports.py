"""Composition Root 为既有运行时协议提供的窄结构端口实现。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

from ..observers import TerminalRenderer
from ..permission_state import PermissionController
from ..runtime.session_identity import SessionIdentityState


class NoticeController:
    """拥有通知回调的最小应用边界，默认输出仍由 Agent module seam 提供。"""

    def __init__(
        self,
        *,
        print_info: Callable[[str], None],
        print_error: Callable[[str], None],
    ) -> None:
        self._print_info = print_info
        self._print_error = print_error
        self._notice_fn: Callable[..., None] | None = None

    def set_notice_fn(
        self,
        fn: Callable[..., None] | None,
    ) -> None:
        self._notice_fn = fn

    def emit(
        self,
        message: str,
        *,
        role: Literal["info", "error"] = "info",
    ) -> None:
        if self._notice_fn is not None:
            self._notice_fn(message, role=role)
        elif role == "error":
            self._print_error(message)
        else:
            self._print_info(message)


class ConfirmationController:
    """工具确认所需的回调与终端提示，不持有 Agent。"""

    def __init__(
        self,
        *,
        permission: PermissionController,
        terminal_output: bool,
        print_confirmation: Callable[[str], None],
        confirm_fn: Callable[[str], Awaitable[bool]] | None,
    ) -> None:
        self.permission = permission
        self.terminal_output = terminal_output
        self._print_confirmation = print_confirmation
        self.confirm_fn = confirm_fn

    async def confirm(self, command: str) -> bool:
        if self.terminal_output:
            self._print_confirmation(command)
        if self.confirm_fn is not None:
            return bool(await self.confirm_fn(command))
        try:
            return input("  Allow? (y/n): ").lower().startswith("y")
        except EOFError:
            return False

    async def confirm_hook_trust(self, message: str) -> bool:
        if self.permission.mode == "dontAsk":
            return False
        return await self.confirm(message)


class SubagentStatusSink:
    """子 Agent 生命周期的 UI 回调边界。"""

    def __init__(
        self,
        *,
        terminal_output: bool,
        start: Callable[[str, str], None],
        end: Callable[[str, str], None],
    ) -> None:
        self.terminal_output = terminal_output
        self._start = start
        self._end = end

    def emit(
        self,
        agent_type: str,
        description: str,
        *,
        started: bool,
    ) -> None:
        if not self.terminal_output:
            return
        if started:
            self._start(agent_type, description)
        else:
            self._end(agent_type, description)


class PlanHost:
    """PlanRuntime 所需的 session id 与通知结构端口。"""

    def __init__(
        self,
        session_state: SessionIdentityState,
        notices: NoticeController,
    ) -> None:
        self._session_state = session_state
        self._notices = notices

    @property
    def session_id(self) -> str:
        return self._session_state.id

    def _emit_notice(
        self,
        message: str,
        *,
        role: Literal["info", "error"] = "info",
    ) -> None:
        self._notices.emit(message, role=role)


class RuntimeIdentityPort:
    """匹配 AgentRuntime 编排访问模式的 identity structural port。

    只暴露 API 就绪态、终端渲染开关与通知；Provider 配置详情不在其中。
    """

    def __init__(
        self,
        *,
        terminal_output: bool,
        api_configured: Callable[[], bool],
        terminal_renderer_factory: Callable[[], TerminalRenderer],
        notices: NoticeController,
    ) -> None:
        self._terminal_output = terminal_output
        self._api_configured = api_configured
        self._terminal_renderer_factory = terminal_renderer_factory
        self._notices = notices

    @property
    def api_configured(self) -> bool:
        return self._api_configured()

    def _create_terminal_renderer(self) -> TerminalRenderer:
        return self._terminal_renderer_factory()

    def _emit_notice(
        self,
        message: str,
        *,
        role: Literal["info", "error"] = "info",
    ) -> None:
        self._notices.emit(message, role=role)


__all__ = [
    "ConfirmationController",
    "NoticeController",
    "PlanHost",
    "RuntimeIdentityPort",
    "SubagentStatusSink",
]
