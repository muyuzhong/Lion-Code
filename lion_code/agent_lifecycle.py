"""Provider 配置与 Thinking 档位的 Agent 生命周期协调。"""

from __future__ import annotations

import os
from collections.abc import Callable, Coroutine
from typing import Any, Protocol

from .agent_runtime import LionAgentRuntime
from .context import (
    ContextCompactor,
    ProviderContextCompactor,
    effective_window_tokens,
    fallback_model_limits,
)
from .core.provider import ModelProvider
from .memory_runtime import MemoryCoordinator, ProviderTextQueryService
from .providers.thinking import (
    ThinkingLevel,
    next_thinking_level,
    normalize_thinking_level,
    provider_thinking_levels,
)
from .session_runtime import SessionRecorder


class AgentLifecycleHost(Protocol):
    """Provider 生命周期所需的 Agent 宿主边界。"""

    use_openai: bool
    model: str
    thinking: bool
    effective_window: int
    _api_key: str
    _api_base: str | None
    _anthropic_base_url: str | None
    _thinking_mode: str
    _thinking_level: ThinkingLevel
    _core_runtime: LionAgentRuntime
    _context_compactor: ContextCompactor | None
    _memory_coordinator: MemoryCoordinator
    _session_recorder: SessionRecorder | None
    _resolved_model_limits_for: tuple[int, str] | None
    _core_compaction_required: bool

    @property
    def is_processing(self) -> bool: ...

    def _resolve_thinking_mode(self) -> str: ...

    def _create_provider(self, **kwargs: Any) -> ModelProvider: ...

    def _schedule_background_operation(
        self,
        operation: Callable[[], Coroutine[Any, Any, object]],
    ) -> None: ...


class AgentLifecycle:
    """在不拥有 Agent 状态的前提下协调 Provider 配置与 Thinking 变更。"""

    def __init__(self, host: AgentLifecycleHost) -> None:
        self._host = host

    @property
    def api_configured(self) -> bool:
        host = self._host
        return bool(host._api_key and (not host.use_openai or host._api_base))

    def get_api_config(self) -> dict[str, bool | str]:
        """返回宿主当前持有的 Provider 配置。"""
        host = self._host
        return {
            "use_openai": host.use_openai,
            "model": host.model,
            "api_key": host._api_key,
            "base_url": (
                host._api_base if host.use_openai else host._anthropic_base_url
            )
            or "",
        }

    def configure_api(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        anthropic_base_url: str | None = None,
        use_openai: bool | None = None,
    ) -> None:
        """空闲态原子切换模型或凭证，并保留现有 canonical history。"""
        host = self._host
        if host.is_processing:
            raise RuntimeError("Agent 运行中，无法切换 Provider 或模型")

        previous_model = host.model
        previous_thinking_level = host._thinking_level
        target_model = model or host.model
        target_use_openai = host.use_openai if use_openai is None else use_openai
        same_protocol = target_use_openai == host.use_openai
        target_api_key = (
            api_key
            if api_key is not None
            else (
                host._api_key
                if same_protocol
                else os.environ.get(
                    "OPENAI_API_KEY" if target_use_openai else "ANTHROPIC_API_KEY",
                    "",
                )
            )
        )
        target_api_base = (
            api_base
            if api_base is not None
            else (
                host._api_base
                if same_protocol and target_use_openai
                else os.environ.get("OPENAI_BASE_URL")
            )
        )
        if target_use_openai and not target_api_base:
            target_api_base = "https://api.openai.com/v1"
        target_anthropic_base_url = (
            anthropic_base_url
            if anthropic_base_url is not None
            else (
                host._anthropic_base_url
                if same_protocol and not target_use_openai
                else os.environ.get("ANTHROPIC_BASE_URL")
            )
        )

        provider_changed = (
            target_use_openai != host.use_openai
            or target_api_key != host._api_key
            or (
                target_api_base != host._api_base
                if target_use_openai
                else target_anthropic_base_url != host._anthropic_base_url
            )
        )
        provider: ModelProvider | None = None
        compactor: ProviderContextCompactor | None = None
        query_service: ProviderTextQueryService | None = None
        if provider_changed:
            provider = self._create_provider_for(
                use_openai=target_use_openai,
                api_key=target_api_key,
                api_base=target_api_base,
                anthropic_base_url=target_anthropic_base_url,
                thinking_level=host._thinking_level,
            )
            compactor = ProviderContextCompactor(
                provider=provider,
                get_model=lambda: host.model,
            )
            query_service = ProviderTextQueryService(
                provider=provider,
                model=lambda: host.model,
            )

        previous_provider: ModelProvider | None = None
        if provider is not None:
            previous_provider = host._core_runtime.replace_provider(provider)
        host.use_openai = target_use_openai
        host._api_key = target_api_key
        host._api_base = target_api_base if target_use_openai else None
        host._anthropic_base_url = (
            target_anthropic_base_url if not target_use_openai else None
        )
        host.model = target_model
        host._core_runtime.set_model(target_model)
        if target_model != previous_model or provider_changed:
            host.effective_window = effective_window_tokens(
                fallback_model_limits(target_model)
            )
            host._resolved_model_limits_for = None
            host._core_compaction_required = False
        if compactor is not None and query_service is not None:
            host._context_compactor = compactor
            host._memory_coordinator.set_query_service(query_service)
        if previous_provider is not None:
            close = getattr(previous_provider, "aclose", None)
            if close is not None:
                host._schedule_background_operation(close)

        self._record_configuration_change(
            previous_model=previous_model,
            previous_thinking_level=previous_thinking_level,
        )

    def set_thinking(self, enabled: bool) -> str:
        """切换兼容 Thinking 模式，并持久化实际生效的历史值。"""
        host = self._host
        previous = host._thinking_mode
        host.thinking = enabled
        host._thinking_mode = host._resolve_thinking_mode()
        recorder = host._session_recorder
        if recorder is not None and host._thinking_mode != previous:
            thinking_value = host._thinking_mode
            host._schedule_background_operation(
                lambda: recorder.record_thinking_level_change(thinking_value)
            )
        return host._thinking_mode

    @property
    def thinking_level(self) -> ThinkingLevel:
        return self._host._thinking_level

    @property
    def available_thinking_levels(self) -> tuple[str, ...]:
        host = self._host
        kind = "openai-compatible" if host.use_openai else "anthropic"
        return provider_thinking_levels(kind, model=host.model)

    def set_thinking_level(self, level: ThinkingLevel | str) -> ThinkingLevel:
        """设定 Core Thinking 档位，热替换 Provider 并记录会话变更。"""
        normalized = normalize_thinking_level(level)
        if normalized == self._host._thinking_level:
            return normalized
        self.apply_core_thinking_level(normalized)
        recorder = self._host._session_recorder
        if recorder is not None:
            host = self._host
            host._schedule_background_operation(
                lambda: recorder.record_thinking_level_change(normalized)
            )
        return normalized

    def cycle_thinking_level(self) -> ThinkingLevel:
        """循环到当前 Provider 可用的下一档 Thinking 级别。"""
        return self.set_thinking_level(
            next_thinking_level(self.thinking_level, self.available_thinking_levels)
        )

    def build_core_provider(self, thinking_level: ThinkingLevel) -> ModelProvider:
        """用宿主当前凭证和指定档位创建 Core Provider。"""
        host = self._host
        return self._create_provider_for(
            use_openai=host.use_openai,
            api_key=host._api_key,
            api_base=host._api_base,
            anthropic_base_url=host._anthropic_base_url,
            thinking_level=thinking_level,
        )

    def apply_core_thinking_level(self, level: ThinkingLevel) -> None:
        """热替换 Provider，使指定 Thinking 档位生效但不记录历史。"""
        host = self._host
        if host.is_processing:
            raise RuntimeError("Agent 运行中，无法切换 thinking 档位")
        provider = self.build_core_provider(level)
        compactor = ProviderContextCompactor(
            provider=provider,
            get_model=lambda: host.model,
        )
        query_service = ProviderTextQueryService(
            provider=provider,
            model=lambda: host.model,
        )
        previous = host._core_runtime.replace_provider(provider)
        host._thinking_level = level
        host._context_compactor = compactor
        host._memory_coordinator.set_query_service(query_service)
        host._resolved_model_limits_for = None
        close = getattr(previous, "aclose", None)
        if close is not None:
            host._schedule_background_operation(close)

    def _create_provider_for(
        self,
        *,
        use_openai: bool,
        api_key: str,
        api_base: str | None,
        anthropic_base_url: str | None,
        thinking_level: ThinkingLevel,
    ) -> ModelProvider:
        if use_openai:
            return self._host._create_provider(
                api_key=api_key,
                api_base=api_base,
                thinking_level=thinking_level,
            )
        return self._host._create_provider(
            api_key=api_key,
            anthropic_base_url=anthropic_base_url,
            thinking_level=thinking_level,
        )

    def _record_configuration_change(
        self,
        *,
        previous_model: str,
        previous_thinking_level: ThinkingLevel,
    ) -> None:
        host = self._host
        recorder = host._session_recorder
        if recorder is None or (
            host.model == previous_model
            and host._thinking_level == previous_thinking_level
        ):
            return
        model_value = host.model
        thinking_value = host._thinking_level

        async def persist_configuration() -> object:
            if model_value != previous_model:
                await recorder.record_model_change(model_value)
            if thinking_value != previous_thinking_level:
                await recorder.record_thinking_level_change(thinking_value)
            return None

        host._schedule_background_operation(persist_configuration)
