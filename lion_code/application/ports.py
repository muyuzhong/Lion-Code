"""Application-owned ports for the coding-session use case.

The protocols in this module describe what ``LionCodingSession`` needs.  They
do not describe a concrete runtime implementation, so adapters can implement
them structurally without importing the application layer.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from lion_code.core.conversation import QueueSnapshot
from lion_code.core.events import AgentEvent
from lion_code.core.messages import AgentMessage

if TYPE_CHECKING:
    from lion_code.permission_state import PermissionMode
    from lion_code.usage import UsageSnapshot

EventListener = Callable[[AgentEvent], Awaitable[None] | None]
ConfirmCallback = Callable[[str], Awaitable[bool]]
PlanApprovalCallback = Callable[[str], Awaitable[dict[str, Any]]]
NoticeCallback = Callable[[str, Literal["info", "error"]], None]


class EgressConfigurationPort(Protocol):
    """Tooling-owned egress settings exposed through an application port."""

    def egress_hosts(self) -> list[str]: ...

    def configure_egress(self, allow_hosts: Sequence[str]) -> list[str]: ...


class ConversationPort(Protocol):
    """Canonical conversation state and run-control primitives."""

    @property
    def messages(self) -> tuple[AgentMessage, ...]: ...

    def subscribe(self, listener: EventListener) -> Callable[[], None]: ...

    async def prompt(self, content: str) -> None: ...

    async def continue_(self) -> None: ...

    def steer(self, content: str) -> QueueSnapshot: ...

    def follow_up(self, content: str) -> QueueSnapshot: ...

    def queue_snapshot(self) -> QueueSnapshot: ...

    def cancel(self) -> None: ...

    @property
    def cancelled(self) -> bool: ...

    async def compact_for_overflow(self) -> bool: ...


class SessionPort(Protocol):
    """Session identity and lifecycle operations."""

    @property
    def session_id(self) -> str: ...

    async def list_sessions(self) -> list[dict[str, Any]]: ...

    async def resume(self, session_id: str) -> bool: ...

    async def rename_session(self, session_id: str, label: str) -> bool: ...

    async def restore_latest(self) -> bool: ...

    async def new_session(self) -> None: ...

    async def compact(self) -> None: ...

    async def aclose(self) -> None: ...


class SettingsPort(Protocol):
    """Provider, permission, workspace, and thinking settings."""

    @property
    def cwd(self) -> Path: ...

    @property
    def model(self) -> str: ...

    @property
    def provider_name(self) -> str: ...

    @property
    def permission_mode(self) -> PermissionMode: ...

    @property
    def api_configured(self) -> bool: ...

    def provider_config(self) -> dict[str, Any]: ...

    def configure_provider(self, **kwargs: Any) -> None: ...

    def egress_hosts(self) -> list[str]: ...

    def configure_egress(self, allow_hosts: Sequence[str]) -> list[str]: ...

    @property
    def thinking_level(self) -> str: ...

    @property
    def available_thinking_levels(self) -> tuple[str, ...]: ...

    def set_thinking_level(self, level: str) -> str: ...

    def cycle_thinking_level(self) -> str: ...

    def set_terminal_output(self, enabled: bool) -> None: ...


class UsagePort(Protocol):
    """Read-only usage projection needed by the application surface."""

    def token_usage(self) -> UsageSnapshot: ...


class ControlPort(Protocol):
    """Instance-scoped frontend callbacks and Plan control."""

    def set_confirm_fn(self, fn: ConfirmCallback | None) -> None: ...

    def set_plan_approval_fn(self, fn: PlanApprovalCallback | None) -> None: ...

    def set_notice_fn(self, fn: NoticeCallback | None) -> None: ...

    def toggle_plan_mode(self) -> str: ...


@runtime_checkable
class CodingSessionBackend(
    ConversationPort,
    SessionPort,
    SettingsPort,
    UsagePort,
    ControlPort,
    Protocol,
):
    """The composed backend contract consumed by ``LionCodingSession``."""


__all__ = [
    "CodingSessionBackend",
    "ConfirmCallback",
    "ControlPort",
    "ConversationPort",
    "EgressConfigurationPort",
    "EventListener",
    "NoticeCallback",
    "PlanApprovalCallback",
    "QueueSnapshot",
    "SessionPort",
    "SettingsPort",
    "UsagePort",
]
