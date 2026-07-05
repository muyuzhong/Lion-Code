from __future__ import annotations

from typing import AsyncIterator, Protocol

from nanoagent.ai.events import AssistantMessageEvent
from nanoagent.ai.messages import Context
from nanoagent.ai.model import Model
from nanoagent.ai.options import StreamOptions


class Provider(Protocol):
    """provider adapter 协议：把 Context 流式转换为 assistant 事件。"""

    def stream(
        self, model: Model, context: Context, options: StreamOptions | None
    ) -> AsyncIterator[AssistantMessageEvent]: ...


_REGISTRY: dict[str, Provider] = {}


def register_provider(api: str, provider: Provider) -> None:
    """注册 provider adapter；api 只是分发键，不代表默认模型选择。"""

    if api == "":
        raise ValueError("api must not be empty")
    _REGISTRY[api] = provider


def get_provider(api: str) -> Provider:
    """按 api 分发键获取 provider。"""

    if api not in _REGISTRY:
        raise KeyError(f"no provider registered for api {api!r}")
    return _REGISTRY[api]


def registered_provider_apis() -> tuple[str, ...]:
    """返回当前已注册 api 的稳定快照，便于测试或 harness introspection。"""

    return tuple(sorted(_REGISTRY))


def clear_providers() -> None:
    """清空 registry，主要用于测试隔离。"""

    _REGISTRY.clear()


def stream(
    model: Model, context: Context, options: StreamOptions | None = None
) -> AsyncIterator[AssistantMessageEvent]:
    """按 model.api 分发；框架不选择 provider，也不发现 API key。"""
    return get_provider(model.api).stream(model, context, options)
