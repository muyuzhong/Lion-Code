"""In-memory backends for application-layer tests."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lion_code.application.ports import EventListener, QueueSnapshot
from lion_code.core.events import AgentEvent
from lion_code.core.messages import AgentMessage
from lion_code.permission_state import PermissionMode
from lion_code.usage import UsageSnapshot


@dataclass
class FakeCodingSessionBackend:
    """Small deterministic backend that implements the application ports."""

    cwd: Path = Path(".")
    model: str = "fake-model"
    provider_name: str = "fake"
    permission_mode: PermissionMode = "default"
    api_configured: bool = True
    plan_mode: bool = False
    messages: tuple[AgentMessage, ...] = ()
    prompt_scripts: list[list[AgentEvent]] = field(default_factory=list)
    continue_scripts: list[list[AgentEvent]] = field(default_factory=list)
    compact_result: bool = True
    wait_for_cancel: bool = False
    sessions: list[dict[str, Any]] = field(default_factory=list)
    session_id: str = "fake-session"
    provider_config_data: dict[str, Any] = field(default_factory=dict)
    egress_configuration: Any | None = None
    thinking_level: str = "off"
    available_thinking_levels: tuple[str, ...] = (
        "off",
        "low",
        "medium",
        "high",
    )
    usage: UsageSnapshot = field(default_factory=UsageSnapshot)

    steering: list[str] = field(default_factory=list, init=False)
    follow_ups: list[str] = field(default_factory=list, init=False)
    prompt_calls: int = field(default=0, init=False)
    continue_calls: int = field(default=0, init=False)
    compact_calls: int = field(default=0, init=False)
    cancel_calls: int = field(default=0, init=False)
    closed: bool = field(default=False, init=False)
    aclose_calls: int = field(default=0, init=False)
    terminal_output: bool = field(default=False, init=False)
    provider_configure_calls: list[dict[str, Any]] = field(
        default_factory=list, init=False
    )
    session_operations: list[tuple[str, str | None]] = field(
        default_factory=list, init=False
    )
    thinking_operations: list[str] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self._listeners: list[EventListener] = []
        self.cancel_event = asyncio.Event()
        self.prompt_started = asyncio.Event()
        self.notice_fn: Callable[[str, str], None] | None = None
        self.confirm_fn: Callable[[str], Awaitable[bool]] | None = None
        self.plan_approval_fn: Callable[[str], Awaitable[dict[str, Any]]] | None = None

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    async def _emit(self, event: AgentEvent) -> None:
        for listener in tuple(self._listeners):
            result = listener(event)
            if asyncio.iscoroutine(result):
                await result

    async def _run_script(self, scripts: list[list[AgentEvent]]) -> None:
        self.prompt_started.set()
        if self.wait_for_cancel:
            await self.cancel_event.wait()
        script = scripts.pop(0) if scripts else []
        for event in script:
            await self._emit(event)

    async def prompt(self, _content: str) -> None:
        self.prompt_calls += 1
        await self._run_script(self.prompt_scripts)

    async def continue_(self) -> None:
        self.continue_calls += 1
        await self._run_script(self.continue_scripts)

    def steer(self, content: str) -> QueueSnapshot:
        self.steering.append(content)
        return self.queue_snapshot()

    def follow_up(self, content: str) -> QueueSnapshot:
        self.follow_ups.append(content)
        return self.queue_snapshot()

    def queue_snapshot(self) -> QueueSnapshot:
        return QueueSnapshot(tuple(self.steering), tuple(self.follow_ups))

    def cancel(self) -> None:
        self.cancel_calls += 1
        self.cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    async def compact_for_overflow(self) -> bool:
        self.compact_calls += 1
        return self.compact_result

    async def list_sessions(self) -> list[dict[str, Any]]:
        self.session_operations.append(("list", None))
        return list(self.sessions)

    async def resume(self, session_id: str) -> bool:
        self.session_operations.append(("resume", session_id))
        return session_id in {str(item.get("id")) for item in self.sessions}

    async def rename_session(self, session_id: str, label: str) -> bool:
        self.session_operations.append(("rename", session_id))
        for item in self.sessions:
            if str(item.get("id")) == session_id:
                item["label"] = label
                return True
        return False

    async def restore_latest(self) -> bool:
        self.session_operations.append(("restore_latest", None))
        return bool(self.sessions)

    async def new_session(self) -> None:
        self.session_operations.append(("new", None))

    async def compact(self) -> None:
        self.session_operations.append(("compact", None))

    async def aclose(self) -> None:
        self.closed = True
        self.aclose_calls += 1

    def provider_config(self) -> dict[str, Any]:
        return dict(self.provider_config_data)

    def configure_provider(self, **kwargs: Any) -> None:
        self.provider_configure_calls.append(dict(kwargs))
        self.provider_config_data.update(kwargs)
        if kwargs.get("model") is not None:
            self.model = str(kwargs["model"])
        if kwargs.get("use_openai") is not None:
            self.provider_name = (
                "openai-compatible" if kwargs["use_openai"] else "anthropic"
            )

    def egress_hosts(self) -> list[str]:
        if self.egress_configuration is None:
            return []
        return self.egress_configuration.configured_hosts()

    def configure_egress(self, allow_hosts: Sequence[str]) -> list[str]:
        if self.egress_configuration is None:
            raise RuntimeError("Egress configuration is unavailable")
        return self.egress_configuration.configure_hosts(allow_hosts)

    def set_thinking_level(self, level: str) -> str:
        self.thinking_operations.append(f"set:{level}")
        if level not in self.available_thinking_levels:
            raise ValueError(level)
        self.thinking_level = level
        return level

    def cycle_thinking_level(self) -> str:
        self.thinking_operations.append("cycle")
        index = self.available_thinking_levels.index(self.thinking_level)
        self.thinking_level = self.available_thinking_levels[
            (index + 1) % len(self.available_thinking_levels)
        ]
        return self.thinking_level

    def set_terminal_output(self, enabled: bool) -> None:
        self.terminal_output = enabled

    def token_usage(self) -> UsageSnapshot:
        return self.usage

    def set_confirm_fn(self, fn: Callable[[str], Awaitable[bool]] | None) -> None:
        self.confirm_fn = fn

    def set_plan_approval_fn(
        self, fn: Callable[[str], Awaitable[dict[str, Any]]] | None
    ) -> None:
        self.plan_approval_fn = fn

    def set_notice_fn(self, fn: Callable[[str, str], None] | None) -> None:
        self.notice_fn = fn

    def toggle_plan_mode(self) -> str:
        self.plan_mode = not self.plan_mode
        return "plan" if self.plan_mode else "default"
