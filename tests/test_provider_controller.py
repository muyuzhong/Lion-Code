"""ProviderController 的状态、事务与窄端口测试。"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from lion_code.runtime.provider import (
    ProviderConfigurationProjection,
    ProviderController,
    ProviderState,
)


class _Provider:
    def __init__(self, label: str) -> None:
        self.label = label
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _Conversation:
    def __init__(self, provider: _Provider) -> None:
        self.provider = provider
        self.model = "model-a"
        self.running = False
        self.events: list[str] = []
        self.retired: list[_Provider] = []

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

    def retire_provider(self, provider: _Provider) -> None:
        self.events.append("retire_provider")
        self.retired.append(provider)


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


class _Recorder:
    def __init__(self) -> None:
        self.changes = []

    def record_configuration_change(self, previous, current) -> None:
        self.changes.append((previous, current))


def _controller(
    *,
    factory,
    conversation: _Conversation | None = None,
    context: _Context | None = None,
    recorder: _Recorder | None = None,
) -> tuple[ProviderController, _Conversation, _Context, _Recorder]:
    conversation = conversation or _Conversation(_Provider("old"))
    context = context or _Context()
    recorder = recorder or _Recorder()
    state = ProviderState(
        model="model-a",
        provider_kind="openai-compatible",
        api_key="key-a",
        openai_base_url="https://old.test/v1",
        anthropic_base_url=None,
        thinking_enabled=False,
        thinking_level="off",
    )
    controller = ProviderController(
        state=state,
        conversation=conversation,
        context=context,
        recorder=recorder,
        provider_factory=factory,
        get_live_model=lambda: conversation.model,
        configuration_projection=ProviderConfigurationProjection(
            _state=state,
            _provider_ready=False,
        ),
    )
    return controller, conversation, context, recorder


def test_view_is_read_only_and_state_has_no_derived_fields() -> None:
    providers = [_Provider("initial")]
    controller, *_ = _controller(
        factory=lambda **_: providers.append(_Provider("new")) or providers[-1]
    )

    assert controller.view.model == "model-a"
    assert controller.view.provider_kind == "openai-compatible"
    assert controller.view.thinking_level == "off"
    with pytest.raises(FrozenInstanceError):
        controller.view.model = "other"


def test_replacement_transaction_refreshes_derived_services_and_retires_old() -> None:
    factory_calls: list[dict] = []

    def factory(**kwargs):
        factory_calls.append(kwargs)
        return _Provider("new")

    controller, conversation, context, recorder = _controller(factory=factory)
    old_provider = conversation.provider
    controller.configure(
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
    assert conversation.events == [
        "replace_provider",
        "set_model",
        "retire_provider",
    ]
    assert context.events == [
        "replace_context_compactor",
        "invalidate_model_limit_cache",
    ]
    assert recorder.changes[0][1].model == "model-b"
    assert conversation.provider.closed is False
    assert old_provider.closed is False
    # 旧 Provider 经 ConversationRuntime 退役命令排程关闭，而不是同步关闭。
    assert conversation.retired == [old_provider]
    assert controller.view.model == "model-b"
    assert controller.view.provider_kind == "openai-compatible"
    projection = controller._configuration_projection
    assert projection.is_api_configured() is True
    assert projection.child_api_kwargs() == {
        "model": "model-b",
        "api_base": "https://new.test/v1",
        "api_key": "key-b",
    }


def test_factory_failure_keeps_conversation_and_view_unchanged() -> None:
    old_provider = _Provider("old")

    def factory(**_kwargs):
        raise RuntimeError("bad provider")

    conversation = _Conversation(old_provider)
    controller, conversation, context, recorder = _controller(
        factory=factory,
        conversation=conversation,
    )
    before = controller.view

    with pytest.raises(RuntimeError, match="bad provider"):
        controller.configure(api_key="key-b")

    assert controller.view == before
    assert conversation.provider is old_provider
    assert conversation.events == []
    assert context.events == []
    assert recorder.changes == []
    assert conversation.retired == []
    assert old_provider.closed is False


def test_model_only_change_uses_conversation_command_without_provider_rebuild() -> None:
    factory_calls: list[dict] = []
    controller, conversation, context, recorder = _controller(
        factory=lambda **kwargs: factory_calls.append(kwargs) or _Provider("unused")
    )

    controller.configure(model="model-b")

    assert factory_calls == []
    assert conversation.events == ["set_model"]
    assert context.events == ["invalidate_model_limit_cache"]
    assert recorder.changes[0][1].model == "model-b"


def test_thinking_and_restore_are_controller_commands() -> None:
    factory_calls: list[dict] = []
    controller, conversation, _context, recorder = _controller(
        factory=lambda **kwargs: (
            factory_calls.append(kwargs) or _Provider("replacement")
        )
    )

    assert controller.set_thinking_level("high") == "high"
    assert controller.view.thinking_level == "high"
    controller.restore_configuration(model="model-restored", thinking_level="adaptive")

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
    assert controller.view.model == "model-restored"
    assert controller.view.thinking_level == "medium"
    assert conversation.model == "model-restored"
    assert len(recorder.changes) == 1
    # 两次 Provider 重建各退役一个旧 Provider。
    assert len(conversation.retired) == 2


def test_build_provider_for_state_reuses_factory_rules() -> None:
    from lion_code.runtime.provider import build_provider_for_state

    calls: list[dict[str, Any]] = []

    def factory(**kwargs):
        calls.append(kwargs)
        return _Provider("built")

    state = ProviderState(
        model="m",
        provider_kind="anthropic",
        api_key="k",
        openai_base_url=None,
        anthropic_base_url="https://anthropic.test",
        thinking_enabled=True,
        thinking_level="medium",
    )
    provider = build_provider_for_state(factory, state, "high")
    assert isinstance(provider, _Provider)
    assert calls == [
        {
            "api_key": "k",
            "anthropic_base_url": "https://anthropic.test",
            "thinking_level": "high",
        }
    ]
