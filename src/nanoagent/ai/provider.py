from __future__ import annotations

from typing import AsyncIterator, Protocol

from nanoagent.ai.events import AssistantMessageEvent
from nanoagent.ai.messages import Context
from nanoagent.ai.model import Model
from nanoagent.ai.options import StreamOptions


class Provider(Protocol):
    def stream(
        self, model: Model, context: Context, options: StreamOptions | None
    ) -> AsyncIterator[AssistantMessageEvent]: ...


_REGISTRY: dict[str, Provider] = {}


def register_provider(api: str, provider: Provider) -> None:
    _REGISTRY[api] = provider


def get_provider(api: str) -> Provider:
    if api not in _REGISTRY:
        raise KeyError(f"no provider registered for api {api!r}")
    return _REGISTRY[api]


def registered_provider_apis() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def clear_providers() -> None:
    _REGISTRY.clear()


def stream(
    model: Model, context: Context, options: StreamOptions | None = None
) -> AsyncIterator[AssistantMessageEvent]:
    """Dispatch by model.api. The framework picks neither provider nor key."""
    return get_provider(model.api).stream(model, context, options)
