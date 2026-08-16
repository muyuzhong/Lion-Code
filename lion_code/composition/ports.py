"""Composition Root 为既有运行时协议提供的窄结构端口实现。"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any, Literal

from ..agent_runtime import AgentRuntimeCoordinator
from ..context import ContextCompactor
from ..core.provider import ModelProvider
from ..domain_ports import NoticeSink
from ..observers import TerminalRenderer
from ..permission_state import PermissionController
from ..provider_manager import (
    ConfigurationRecorder,
    ModelContextControl,
    ProviderRuntimePort,
    ProviderView,
)
from ..session_identity import SessionIdentityState
from ..session_runtime import SessionRecorder, SessionRepository


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


class NoticeSinkAdapter(NoticeSink):
    """把有关键字参数的通知控制器适配成 Domain NoticeSink。"""

    def __init__(self, controller: NoticeController) -> None:
        self._controller = controller

    def emit(
        self,
        message: str,
        *,
        role: Literal["info", "error"] = "info",
    ) -> None:
        self._controller.emit(message, role=role)


class ConfirmationController:
    """工具确认所需的回调与终端提示，不持有 Agent。"""

    def __init__(
        self,
        *,
        permission: PermissionController,
        terminal_output: bool,
        print_confirmation: Callable[[str], None],
        confirm_fn: Callable[[str], Any] | None,
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
    """匹配 RuntimeCoordinator 实际访问模式的 identity structural port。"""

    def __init__(
        self,
        *,
        is_sub_agent: bool,
        terminal_output: bool,
        effective_window: int,
        api_configured: Callable[[], bool],
        is_aborted: Callable[[], bool],
        terminal_renderer_factory: Callable[[], TerminalRenderer],
        notices: NoticeController,
    ) -> None:
        self.is_sub_agent = is_sub_agent
        self._terminal_output = terminal_output
        self._last_stop_reason: str | None = None
        self.effective_window = effective_window
        self._api_configured = api_configured
        self._is_aborted = is_aborted
        self._terminal_renderer_factory = terminal_renderer_factory
        self._notices = notices

    @property
    def api_configured(self) -> bool:
        return self._api_configured()

    @property
    def is_aborted(self) -> bool:
        return self._is_aborted()

    def _create_terminal_renderer(self) -> TerminalRenderer:
        return self._terminal_renderer_factory()

    def _emit_notice(
        self,
        message: str,
        *,
        role: Literal["info", "error"] = "info",
    ) -> None:
        self._notices.emit(message, role=role)


class SessionStatePort:
    """匹配 RuntimeCoordinator session 访问模式的 structural port。"""

    def __init__(
        self,
        *,
        session_state: SessionIdentityState,
        session_repository: SessionRepository,
        tool_context: Any,
    ) -> None:
        self._session_state = session_state
        self._session_repository = session_repository
        self.tool_context = tool_context

    @property
    def session_state(self) -> SessionIdentityState:
        return self._session_state


class DeferredProviderRuntimePort(ProviderRuntimePort):
    """ProviderManager 与 Core Runtime 之间的 construction-order port。"""

    def __init__(self) -> None:
        self._runtime: AgentRuntimeCoordinator | None = None

    def bind(self, runtime: AgentRuntimeCoordinator) -> None:
        self._runtime = runtime

    @property
    def is_running(self) -> bool:
        return (
            self._runtime is not None and self._runtime.core_runtime.harness.is_running
        )

    def replace_provider(self, provider: ModelProvider) -> ModelProvider:
        if self._runtime is None:
            raise RuntimeError("Provider Runtime 尚未初始化")
        return self._runtime.core_runtime.replace_provider(provider)

    def set_model(self, model: str) -> None:
        if self._runtime is None:
            raise RuntimeError("Provider Runtime 尚未初始化")
        self._runtime.core_runtime.set_model(model)


class DeferredModelContextControl(ModelContextControl):
    """把 Provider 派生更新转交给已创建的 RuntimeCoordinator。"""

    def __init__(self) -> None:
        self._runtime: AgentRuntimeCoordinator | None = None

    def bind(self, runtime: AgentRuntimeCoordinator) -> None:
        self._runtime = runtime

    def replace_context_compactor(self, compactor: ContextCompactor) -> None:
        if self._runtime is None:
            raise RuntimeError("Provider Runtime 尚未初始化")
        self._runtime.replace_context_compactor(compactor)

    def invalidate_model_limit_cache(self, model: str) -> None:
        if self._runtime is None:
            raise RuntimeError("Provider Runtime 尚未初始化")
        self._runtime.invalidate_model_limit_cache(model)


class SessionRecorderConfigurationRecorder(ConfigurationRecorder):
    """把同步 Provider 配置变化适配到异步 SessionRecorder。"""

    def __init__(self) -> None:
        self._recorder: Callable[[], SessionRecorder | None] | None = None
        self._schedule: (
            Callable[[Callable[[], Coroutine[Any, Any, object]]], None] | None
        ) = None

    def bind(
        self,
        recorder: Callable[[], SessionRecorder | None],
        schedule: Callable[[Callable[[], Coroutine[Any, Any, object]]], None],
    ) -> None:
        self._recorder = recorder
        self._schedule = schedule

    def record_configuration_change(
        self,
        previous: ProviderView,
        current: ProviderView,
    ) -> None:
        recorder_getter = self._recorder
        schedule = self._schedule
        if recorder_getter is None or schedule is None:
            return
        recorder = recorder_getter()
        if recorder is None:
            return
        model_changed = previous.model != current.model
        thinking_level_changed = previous.thinking_level != current.thinking_level
        thinking_mode_changed = previous.thinking_mode != current.thinking_mode
        if not (model_changed or thinking_level_changed or thinking_mode_changed):
            return

        async def persist_configuration() -> object:
            if model_changed:
                await recorder.record_model_change(current.model)
            if thinking_level_changed:
                await recorder.record_thinking_level_change(current.thinking_level)
            elif thinking_mode_changed:
                await recorder.record_thinking_level_change(current.thinking_mode)
            return None

        schedule(persist_configuration)


class DeferredBackgroundScheduler:
    """RuntimeCoordinator 创建后才可用的后台任务调度端口。"""

    def __init__(self) -> None:
        self._runtime: AgentRuntimeCoordinator | None = None

    def bind(self, runtime: AgentRuntimeCoordinator) -> None:
        self._runtime = runtime

    def __call__(
        self,
        operation: Callable[[], Coroutine[Any, Any, object]],
    ) -> None:
        if self._runtime is None:
            raise RuntimeError("Provider Runtime 尚未初始化")
        self._runtime.schedule_background_operation(operation)
