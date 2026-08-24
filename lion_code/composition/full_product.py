"""FullProfile 产品的 Composition/Bootstrap 入口。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ..adapters.coding_session_backend import CodingSessionBackendAdapter
from ..hooks import load_pre_tool_use_hooks
from ..meta_agent import MetaAgent
from ..observers import TerminalRenderer
from ..permission_state import PermissionMode
from ..prompt import build_dynamic_system_context
from ..providers.factory import create_provider
from ..session_runtime import SessionRepository
from ..tooling import ToolRegistry
from ..ui import (
    print_confirmation,
    print_error,
    print_info,
    print_sub_agent_end,
    print_sub_agent_start,
)
from . import (
    AgentConfig,
    FullProfile,
    InteractionBindings,
    ProviderBindings,
    RuntimeBindings,
    SessionBindings,
    ToolBindings,
    build_agent_composition,
)


def _full_provider_factory(**kwargs: Any):
    return create_provider(**kwargs)


def _full_dynamic_context_builder(names) -> str:
    return build_dynamic_system_context(list(names))


def _full_terminal_renderer_factory() -> TerminalRenderer:
    return TerminalRenderer()


def build_full_coding_backend(
    *,
    permission_mode: PermissionMode = "default",
    model: str = "claude-opus-4-6",
    api_base: str | None = None,
    anthropic_base_url: str | None = None,
    api_key: str | None = None,
    thinking: bool = False,
    max_cost_usd: float | None = None,
    max_turns: int | None = None,
    terminal_output: bool = True,
    custom_system_prompt: str | None = None,
    session_repository: SessionRepository | None = None,
    confirm_fn: Callable[[str], Awaitable[bool]] | None = None,
    tool_registry: ToolRegistry | None = None,
) -> CodingSessionBackendAdapter:
    """装配 FullProfile 产品：Composition → MetaAgent → Product Adapter。"""

    config = AgentConfig(
        permission_mode=permission_mode,
        model=model,
        api_base=api_base,
        anthropic_base_url=anthropic_base_url,
        api_key=api_key,
        thinking=thinking,
        max_cost_usd=max_cost_usd,
        max_turns=max_turns,
        terminal_output=terminal_output,
    )
    bindings = RuntimeBindings(
        provider=ProviderBindings(
            provider_factory=_full_provider_factory,
        ),
        session=SessionBindings(
            session_repository=session_repository,
        ),
        tool=ToolBindings(
            tool_registry=tool_registry,
            pre_tool_use_hooks_loader=load_pre_tool_use_hooks,
        ),
        interaction=InteractionBindings(
            confirm_fn=confirm_fn,
            dynamic_system_context_builder=_full_dynamic_context_builder,
            terminal_renderer_factory=_full_terminal_renderer_factory,
            print_info=print_info,
            print_error=print_error,
            print_confirmation=print_confirmation,
            print_sub_agent_start=print_sub_agent_start,
            print_sub_agent_end=print_sub_agent_end,
        ),
    )
    composition = build_agent_composition(
        FullProfile(system_prompt=custom_system_prompt),
        config=config,
        bindings=bindings,
    )
    # Full Profile 固定组合全部内置能力，Feature 字段必然存在。
    assert composition.capabilities.plan is not None
    assert composition.capabilities.subagent_factory is not None
    assert composition.capabilities.subagent_executor is not None
    assert composition.capabilities.skill_runtime is not None
    assert composition.interaction.status_sink is not None

    runtime = composition.runtime
    agent = MetaAgent(
        agent_runtime=runtime.agent,
        provider_controller=runtime.provider_controller,
        conversation=runtime.conversation,
        session=runtime.session,
        usage=runtime.usage,
        budget=runtime.budget,
        permission_mode=config.permission_mode,
    )
    return CodingSessionBackendAdapter(
        agent=agent,
        plan=composition.capabilities.plan,
        confirmation=composition.interaction.confirmation,
        notices=composition.interaction.notices,
        status_sink=composition.interaction.status_sink,
        terminal_output_sink=runtime.agent.set_terminal_output,
        session_renamer=runtime.session.rename_session,
        session_repository=runtime.session.repository,
        cwd=Path(composition.tooling.context.cwd),
    )


__all__ = ["build_full_coding_backend"]
