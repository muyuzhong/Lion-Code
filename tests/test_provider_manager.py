"""ProviderManager 的状态、事务与窄端口测试。"""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from lion_code.provider_manager import ProviderManager, ProviderState


class _Provider:
    def __init__(self, label: str) -> None:
        self.label = label
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _Runtime:
    def __init__(self, provider: _Provider) -> None:
        self.provider = provider
        self.model = "model-a"
        self.running = False
        self.events: list[str] = []

    @property
    def is_running(self) -> bool:
        return self.running

    def replace_provider(self, provider: _Provider) -> _Provider:
        self.events.append("replace_provider")
        previous = self.provider
        self.provider = provider
        return previous

    def set_model(self, model: str) -> None:
        self.events.append("set_model")
        self.model = model


class _Context:
    def __init__(self) -> None:
        self.compactor = None
        self.invalidated: list[str] = []
        self.events: list[str] = []

    def replace_context_compactor(self, compactor) -> None:
        self.events.append("replace_context_compactor")
        self.compactor = compactor

    def invalidate_model_limit_cache(self, model: str) -> None:
        self.events.append("invalidate_model_limit_cache")
        self.invalidated.append(model)


class _Memory:
    def __init__(self) -> None:
        self.service = None
        self.events: list[str] = []

    def set_query_service(self, service) -> None:
        self.events.append("set_query_service")
        self.service = service


class _Recorder:
    def __init__(self) -> None:
        self.changes = []

    def record_configuration_change(self, previous, current) -> None:
        self.changes.append((previous, current))


def _manager(
    *,
    factory,
    runtime: _Runtime | None = None,
    context: _Context | None = None,
    memory: _Memory | None = None,
    recorder: _Recorder | None = None,
    scheduled: list[Any] | None = None,
) -> tuple[ProviderManager, _Runtime, _Context, _Memory, _Recorder, list[Any]]:
    runtime = runtime or _Runtime(_Provider("old"))
    context = context or _Context()
    memory = memory or _Memory()
    recorder = recorder or _Recorder()
    scheduled = [] if scheduled is None else scheduled
    manager = ProviderManager(
        state=ProviderState(
            model="model-a",
            provider_kind="openai-compatible",
            api_key="key-a",
            openai_base_url="https://old.test/v1",
            anthropic_base_url=None,
            thinking_enabled=False,
            thinking_level="off",
        ),
        runtime=runtime,
        context=context,
        memory=memory,
        recorder=recorder,
        provider_factory=factory,
        schedule_background_operation=scheduled.append,
    )
    return manager, runtime, context, memory, recorder, scheduled


def test_view_is_read_only_and_state_has_no_derived_fields() -> None:
    providers = [_Provider("initial")]
    manager, *_ = _manager(
        factory=lambda **_: providers.append(_Provider("new")) or providers[-1]
    )

    assert manager.view.model == "model-a"
    assert manager.view.provider_kind == "openai-compatible"
    assert manager.view.thinking_level == "off"
    with pytest.raises(FrozenInstanceError):
        manager.view.model = "other"


def test_replacement_transaction_refreshes_derived_services_before_old_close() -> None:
    factory_calls: list[dict] = []

    def factory(**kwargs):
        factory_calls.append(kwargs)
        return _Provider("new")

    manager, runtime, context, memory, recorder, scheduled = _manager(factory=factory)
    old_provider = runtime.provider
    manager.configure(
        model="model-b",
        api_key="key-b",
        api_base="https://new.test/v1",
    )

    assert factory_calls == [
        {
            "api_key": "key-b",
            "api_base": "https://new.test/v1",
            "thinking_level": "off",
        }
    ]
    assert runtime.events == ["replace_provider", "set_model"]
    assert context.events == [
        "replace_context_compactor",
        "invalidate_model_limit_cache",
    ]
    assert memory.events == ["set_query_service"]
    assert recorder.changes[0][1].model == "model-b"
    assert runtime.provider.closed is False
    assert old_provider.closed is False

    asyncio.run(scheduled[0]())
    assert old_provider.closed is True
    assert manager.view.model == "model-b"
    assert manager.view.provider_kind == "openai-compatible"


def test_factory_failure_keeps_runtime_and_view_unchanged() -> None:
    old_provider = _Provider("old")

    def factory(**_kwargs):
        raise RuntimeError("bad provider")

    runtime = _Runtime(old_provider)
    manager, _, context, memory, recorder, scheduled = _manager(
        factory=factory,
        runtime=runtime,
    )
    before = manager.view

    with pytest.raises(RuntimeError, match="bad provider"):
        manager.configure(api_key="key-b")

    assert manager.view == before
    assert runtime.provider is old_provider
    assert runtime.events == []
    assert context.events == []
    assert memory.events == []
    assert recorder.changes == []
    assert scheduled == []
    assert old_provider.closed is False


def test_model_only_change_uses_runtime_command_without_provider_rebuild() -> None:
    factory_calls: list[dict] = []
    manager, runtime, context, memory, recorder, _ = _manager(
        factory=lambda **kwargs: factory_calls.append(kwargs) or _Provider("unused")
    )

    manager.configure(model="model-b")

    assert factory_calls == []
    assert runtime.events == ["set_model"]
    assert context.events == ["invalidate_model_limit_cache"]
    assert memory.events == []
    assert recorder.changes[0][1].model == "model-b"


def test_thinking_and_restore_are_manager_commands() -> None:
    factory_calls: list[dict] = []
    manager, runtime, _context, memory, recorder, scheduled = _manager(
        factory=lambda **kwargs: (
            factory_calls.append(kwargs) or _Provider("replacement")
        )
    )

    assert manager.set_thinking_level("high") == "high"
    assert manager.view.thinking_level == "high"
    manager.restore_configuration(model="model-restored", thinking_level="adaptive")

    assert factory_calls == [
        {
            "api_key": "key-a",
            "api_base": "https://old.test/v1",
            "thinking_level": "high",
        },
        {
            "api_key": "key-a",
            "api_base": "https://old.test/v1",
            "thinking_level": "medium",
        },
    ]
    assert manager.view.model == "model-restored"
    assert manager.view.thinking_level == "medium"
    assert runtime.model == "model-restored"
    assert len(memory.events) == 2
    assert len(recorder.changes) == 1
    assert len(scheduled) == 2
