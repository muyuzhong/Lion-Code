"""Provider 配置、模型与 Thinking 生命周期的唯一状态所有者。"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from ..context import (
    ContextCompactor,
    ProviderContextCompactor,
)
from ..core.provider import ModelProvider
from ..providers.thinking import (
    ThinkingLevel,
    coerce_thinking_level,
    next_thinking_level,
    normalize_thinking_level,
    provider_thinking_levels,
)

ProviderKind = Literal["anthropic", "openai-compatible"]
ProviderReadinessBlockerCode = Literal["provider_configuration_required"]
ProviderFactory = Callable[..., ModelProvider]


@dataclass(frozen=True, slots=True)
class ProviderReadiness:
    """当前 Provider 配置是否可发送请求的不可变快照。"""

    ready: bool
    blocker_code: ProviderReadinessBlockerCode | None


@dataclass(slots=True)
class ProviderState:
    """Provider 配置的可变权威状态，只由 ``ProviderController`` 提交更新。"""

    model: str
    provider_kind: ProviderKind
    api_key: str
    openai_base_url: str | None
    anthropic_base_url: str | None
    thinking_enabled: bool
    thinking_level: ThinkingLevel


@dataclass(slots=True)
class ProviderConfigurationProjection:
    """供 Runtime/Capability 读取当前 Provider 配置的稳定只读投影。

    Composition Root 在 ``ProviderController`` 之前创建此对象；投影只保存
    当前权威 ``ProviderState`` 的引用，不持有 Controller，也不复制可写状态。
    Controller 仅在成功提交新的 state 后同步引用，避免读取面反向捕获未来
    Controller。
    """

    _state: ProviderState
    _provider_ready: bool

    def readiness(self) -> ProviderReadiness:
        state = self._state
        ready = self._provider_ready or bool(
            state.api_key
            and (
                state.provider_kind == "anthropic" or bool(state.openai_base_url)
            )
        )
        return ProviderReadiness(
            ready=ready,
            blocker_code=None if ready else "provider_configuration_required",
        )

    def is_api_configured(self) -> bool:
        return self.readiness().ready

    def child_api_kwargs(self) -> dict[str, str | None]:
        """返回子 Agent 继承当前 Provider 所需的凭证与 base projection。"""

        state = self._state
        if state.provider_kind == "openai-compatible":
            return {
                "model": state.model,
                "api_base": state.openai_base_url,
                "api_key": state.api_key,
            }
        return {
            "model": state.model,
            "api_base": None,
            "anthropic_base_url": state.anthropic_base_url,
            "api_key": state.api_key,
        }

    def _sync(self, state: ProviderState) -> None:
        """由 ProviderController 在 state 提交后刷新共享引用。"""

        self._state = state


@dataclass(frozen=True, slots=True)
class ProviderView:
    """供应用和 Session 消费的 Provider 只读投影。"""

    model: str
    provider_kind: ProviderKind
    thinking_enabled: bool
    thinking_level: ThinkingLevel

    @property
    def thinking_mode(self) -> str:
        """返回旧布尔 Thinking API 的派生模式，不把它写回 ProviderState。"""

        if not self.thinking_enabled:
            return "disabled"
        if not _model_supports_thinking(self.model):
            return "disabled"
        if _model_supports_adaptive_thinking(self.model):
            return "adaptive"
        return "enabled"


class ProviderRuntimePort(Protocol):
    """ConversationRuntime 暴露给 ProviderController 的 live Provider/model 命令。"""

    @property
    def is_running(self) -> bool: ...

    def replace_provider(self, provider: ModelProvider) -> ModelProvider: ...

    def set_model(self, model: str) -> None: ...

    def retire_provider(self, provider: ModelProvider) -> None: ...


class ModelContextControl(Protocol):
    """ContextRuntime 暴露给 ProviderController 的派生服务命令。"""

    def replace_context_compactor(self, compactor: ContextCompactor) -> None: ...

    def invalidate_model_limit_cache(self, model: str) -> None: ...


class ConfigurationRecorder(Protocol):
    """SessionRuntime 暴露给 ProviderController 的配置变更记录端口。"""

    def record_configuration_change(
        self,
        previous: ProviderView,
        current: ProviderView,
    ) -> None: ...


def _model_supports_thinking(model: str) -> bool:
    model_name = model.lower()
    if "claude-3-" in model_name or "3-5-" in model_name or "3-7-" in model_name:
        return False
    if "claude" in model_name and any(
        marker in model_name for marker in ("opus", "sonnet", "haiku")
    ):
        return True
    return False


def _model_supports_adaptive_thinking(model: str) -> bool:
    model_name = model.lower()
    return "opus-4-6" in model_name or "sonnet-4-6" in model_name


def build_provider_for_state(
    factory: ProviderFactory,
    state: ProviderState,
    level: ThinkingLevel,
) -> ModelProvider:
    """按 ProviderState 构建一个尚未安装的 Provider 实例。

    Composition Root 用它构建 initial provider；ProviderController 用它构建
    切换目标 provider。两者共享同一构造规则，不重复实现。
    """

    if state.provider_kind == "openai-compatible":
        return factory(
            api_key=state.api_key,
            api_base=state.openai_base_url,
            thinking_level=level,
        )
    return factory(
        api_key=state.api_key,
        anthropic_base_url=state.anthropic_base_url,
        thinking_level=level,
    )


class ProviderController:
    """拥有 ProviderState，并以命令方式完成配置与 Thinking 变更。

    只通过三个窄端口对外作用，不持有 AgentRuntime，也不被其反向持有：
    - ``conversation`` -- replace_provider / set_model / retire_provider / is_running
    - ``context`` -- 派生 compactor 与模型限制缓存失效
    - ``recorder`` -- 配置变更 Entry 记录（SessionRuntime 窄端口）

    所有可能失败的 Provider 与派生服务都在 Runtime/State 变更前构建；
    成功后才按固定顺序提交并刷新外部投影。
    """

    def __init__(
        self,
        *,
        state: ProviderState,
        conversation: ProviderRuntimePort,
        context: ModelContextControl,
        recorder: ConfigurationRecorder,
        provider_factory: ProviderFactory,
        get_live_model: Callable[[], str],
        configuration_projection: ProviderConfigurationProjection,
    ) -> None:
        self._state = state
        self._conversation = conversation
        self._context = context
        self._recorder = recorder
        self._provider_factory = provider_factory
        self._get_live_model = get_live_model
        self._configuration_projection = configuration_projection

    @property
    def view(self) -> ProviderView:
        """返回不包含凭证与可写状态引用的快照。"""

        state = self._state
        return ProviderView(
            model=state.model,
            provider_kind=state.provider_kind,
            thinking_enabled=state.thinking_enabled,
            thinking_level=state.thinking_level,
        )

    @property
    def model(self) -> str:
        return self._state.model

    @property
    def provider_kind(self) -> ProviderKind:
        return self._state.provider_kind

    @property
    def provider_name(self) -> str:
        return self._state.provider_kind

    @property
    def use_openai(self) -> bool:
        return self._state.provider_kind == "openai-compatible"

    @property
    def thinking(self) -> bool:
        return self._state.thinking_enabled

    @property
    def thinking_level(self) -> ThinkingLevel:
        return self._state.thinking_level

    @property
    def available_thinking_levels(self) -> tuple[ThinkingLevel, ...]:
        return provider_thinking_levels(self.provider_kind, model=self.model)

    @property
    def provider_readiness(self) -> ProviderReadiness:
        return self._configuration_projection.readiness()

    @property
    def api_configured(self) -> bool:
        return self.provider_readiness.ready

    def get_api_config(self) -> dict[str, bool | str]:
        """返回兼容 API 的配置投影；凭证仍只在明确命令中暴露。"""

        state = self._state
        return {
            "use_openai": state.provider_kind == "openai-compatible",
            "model": state.model,
            "api_key": state.api_key,
            "base_url": self._active_base_url() or "",
        }

    def configure(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        anthropic_base_url: str | None = None,
        use_openai: bool | None = None,
    ) -> None:
        """在空闲态原子切换模型、Provider 或凭证。"""

        self._reject_if_running("Agent 运行中，无法切换 Provider 或模型")
        current = self._state
        target = self._resolve_target_state(
            current,
            model=model,
            api_key=api_key,
            api_base=api_base,
            anthropic_base_url=anthropic_base_url,
            use_openai=use_openai,
            thinking_level=current.thinking_level,
        )
        if target == current:
            return
        self._apply_target_state(target, previous=current, record=True)

    def set_thinking_level(self, level: ThinkingLevel | str) -> ThinkingLevel:
        """热替换 Provider 以应用新档位，并记录档位变化。"""

        normalized = normalize_thinking_level(level)
        current = self._state
        target = ProviderState(
            model=current.model,
            provider_kind=current.provider_kind,
            api_key=current.api_key,
            openai_base_url=current.openai_base_url,
            anthropic_base_url=current.anthropic_base_url,
            thinking_enabled=current.thinking_enabled,
            thinking_level=normalized,
        )
        self._reject_if_running("Agent 运行中，无法切换 thinking 档位")
        self._apply_target_state(
            target,
            previous=current,
            record=normalized != current.thinking_level,
            force_provider_rebuild=True,
        )
        return normalized

    def cycle_thinking_level(self) -> ThinkingLevel:
        """循环到当前 Provider 可用的下一档 Thinking 级别。"""

        return self.set_thinking_level(
            next_thinking_level(self.thinking_level, self.available_thinking_levels)
        )

    def restore_configuration(
        self,
        *,
        model: str | None = None,
        thinking_level: str | None = None,
    ) -> None:
        """恢复 JSONL 中的 model/thinking，不追加新的配置 Entry。"""

        current = self._state
        target_model = model or current.model
        target_level = (
            coerce_thinking_level(thinking_level)
            if thinking_level is not None
            else current.thinking_level
        )
        if target_model == current.model and target_level == current.thinking_level:
            return
        target = ProviderState(
            model=target_model,
            provider_kind=current.provider_kind,
            api_key=current.api_key,
            openai_base_url=current.openai_base_url,
            anthropic_base_url=current.anthropic_base_url,
            thinking_enabled=current.thinking_enabled,
            thinking_level=target_level,
        )
        self._reject_if_running("Agent 运行中，无法恢复 Provider 配置")
        self._apply_target_state(target, previous=current, record=False)

    def build_provider(
        self,
        level: ThinkingLevel | str | None = None,
    ) -> ModelProvider:
        """按当前配置构建 Provider，但不安装或替换活跃 Runtime。"""

        normalized = (
            self._state.thinking_level
            if level is None
            else normalize_thinking_level(level)
        )
        return build_provider_for_state(
            self._provider_factory,
            self._state,
            normalized,
        )

    def _resolve_target_state(
        self,
        current: ProviderState,
        *,
        model: str | None,
        api_key: str | None,
        api_base: str | None,
        anthropic_base_url: str | None,
        use_openai: bool | None,
        thinking_level: ThinkingLevel,
    ) -> ProviderState:
        target_kind: ProviderKind = (
            current.provider_kind
            if use_openai is None
            else ("openai-compatible" if use_openai else "anthropic")
        )
        same_kind = target_kind == current.provider_kind
        target_key = (
            api_key
            if api_key is not None
            else (
                current.api_key
                if same_kind
                else os.environ.get(
                    "OPENAI_API_KEY"
                    if target_kind == "openai-compatible"
                    else "ANTHROPIC_API_KEY",
                    "",
                )
            )
        )
        if target_kind == "openai-compatible":
            target_openai_base = (
                api_base
                if api_base is not None
                else (
                    current.openai_base_url
                    if same_kind
                    else os.environ.get("OPENAI_BASE_URL")
                )
            ) or "https://api.openai.com/v1"
            target_anthropic_base = None
        else:
            target_openai_base = None
            target_anthropic_base = (
                anthropic_base_url
                if anthropic_base_url is not None
                else (
                    current.anthropic_base_url
                    if same_kind
                    else os.environ.get("ANTHROPIC_BASE_URL")
                )
            )
        return ProviderState(
            model=model or current.model,
            provider_kind=target_kind,
            api_key=target_key,
            openai_base_url=target_openai_base,
            anthropic_base_url=target_anthropic_base,
            thinking_enabled=current.thinking_enabled,
            thinking_level=thinking_level,
        )

    def _apply_target_state(
        self,
        target: ProviderState,
        *,
        previous: ProviderState,
        record: bool,
        force_provider_rebuild: bool = False,
    ) -> None:
        provider_changed = (
            force_provider_rebuild
            or self._provider_configuration_changed(previous, target)
        )
        model_changed = previous.model != target.model
        provider: ModelProvider | None = None
        compactor: ProviderContextCompactor | None = None
        if provider_changed:
            provider = build_provider_for_state(
                self._provider_factory,
                target,
                target.thinking_level,
            )
            compactor = ProviderContextCompactor(
                provider=provider,
                get_model=self._get_live_model,
            )

        previous_provider: ModelProvider | None = None
        if provider is not None:
            try:
                previous_provider = self._conversation.replace_provider(provider)
                self._conversation.set_model(target.model)
            except BaseException:
                if previous_provider is not None:
                    self._conversation.replace_provider(previous_provider)
                    self._conversation.set_model(previous.model)
                self._conversation.retire_provider(provider)
                raise
        elif model_changed:
            self._conversation.set_model(target.model)

        self._state = target
        self._configuration_projection._sync(target)
        if provider_changed:
            assert compactor is not None
            self._context.replace_context_compactor(compactor)
            self._context.invalidate_model_limit_cache(target.model)
        elif model_changed:
            self._context.invalidate_model_limit_cache(target.model)

        if record:
            self._recorder.record_configuration_change(
                self._view_for(previous),
                self.view,
            )
        if previous_provider is not None:
            self._conversation.retire_provider(previous_provider)

    def _provider_configuration_changed(
        self,
        previous: ProviderState,
        current: ProviderState,
    ) -> bool:
        return (
            previous.provider_kind != current.provider_kind
            or previous.api_key != current.api_key
            or previous.openai_base_url != current.openai_base_url
            or previous.anthropic_base_url != current.anthropic_base_url
            or previous.thinking_level != current.thinking_level
        )

    def _active_base_url(self) -> str | None:
        state = self._state
        return (
            state.openai_base_url
            if state.provider_kind == "openai-compatible"
            else state.anthropic_base_url
        )

    def _view_for(self, state: ProviderState) -> ProviderView:
        return ProviderView(
            model=state.model,
            provider_kind=state.provider_kind,
            thinking_enabled=state.thinking_enabled,
            thinking_level=state.thinking_level,
        )

    def _reject_if_running(self, message: str) -> None:
        if self._conversation.is_running:
            raise RuntimeError(message)


__all__ = [
    "ConfigurationRecorder",
    "ModelContextControl",
    "ProviderConfigurationProjection",
    "ProviderController",
    "ProviderFactory",
    "ProviderKind",
    "ProviderReadiness",
    "ProviderReadinessBlockerCode",
    "ProviderRuntimePort",
    "ProviderState",
    "ProviderView",
    "build_provider_for_state",
]
