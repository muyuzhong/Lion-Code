"""Provider contract owned by Lion's portable agent layer."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from lion_code.core.cancellation import CancellationView
from lion_code.core.messages import AgentMessage
from lion_code.core.provider_events import AssistantMessageEvent
from lion_code.core.tools import AgentTool


class ModelProvider(Protocol):
    """Provider-neutral Pi-compatible model stream interface."""

    def stream_response(
        self,
        *,
        model: str,
        system: str,
        messages: list[AgentMessage],
        tools: list[AgentTool],
        signal: CancellationView | None = None,
    ) -> AsyncIterator[AssistantMessageEvent]:
        """Stream one model response as assistant message events."""
        ...
