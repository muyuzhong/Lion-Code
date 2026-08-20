"""测试用 Full 组合构造 helper：真实公共路径 build_agent_composition + MetaAgent。

旧 ``lion_code.agent.Agent`` 删除后，需要断言 composition 内部结构或
``run``/``run_once`` 等通用 facade 契约的测试统一经此构造；产品级行为
测试应使用 ``build_full_coding_backend``。

本模块从 ``lion_code.ui`` 等模块导入默认绑定，monkeypatch 目标
（``tests.full_agent.create_provider`` 等）与旧 ``lion_code.agent.*``
seam 语义一致。
"""

from __future__ import annotations

from dataclasses import dataclass

from lion_code.composition import (
    AgentConfig,
    FullProfile,
    InteractionBindings,
    ProviderBindings,
    RuntimeBindings,
    SessionBindings,
    ToolBindings,
    build_agent_composition,
)
from lion_code.composition.agent_builder import AgentComposition
from lion_code.hooks import load_pre_tool_use_hooks
from lion_code.meta_agent import MetaAgent
from lion_code.observers import TerminalRenderer
from lion_code.permission_state import PermissionMode
from lion_code.prompt import build_dynamic_system_context
from lion_code.providers.factory import create_provider
from lion_code.session_runtime import SessionRepository
from lion_code.tooling import ToolRegistry
from lion_code.ui import (
    print_confirmation,
    print_error,
    print_info,
    print_sub_agent_end,
    print_sub_agent_start,
)


def _provider_factory(**kwargs):
    return create_provider(**kwargs)


def _print_info(message: str) -> None:
    print_info(message)


def _print_error(message: str) -> None:
    print_error(message)


def _print_confirmation(message: str) -> None:
    print_confirmation(message)


def _print_subagent_start(agent_type: str, description: str) -> None:
    print_sub_agent_start(agent_type, description)


def _print_subagent_end(agent_type: str, description: str) -> None:
    print_sub_agent_end(agent_type, description)


def _dynamic_context_builder(names) -> str:
    return build_dynamic_system_context(list(names))


def _terminal_renderer_factory() -> TerminalRenderer:
    return TerminalRenderer()


@dataclass(slots=True)
class FullAgentHarness:
    """Full 组合 + 通用 facade：测试按需取 composition 分层字段。"""

    composition: AgentComposition
    agent: MetaAgent


def build_full_agent_harness(
    *,
    permission_mode: PermissionMode = "default",
    model: str = "claude-opus-4-6",
    api_base: str | None = None,
    anthropic_base_url: str | None = None,
    api_key: str | None = None,
    thinking: bool = False,
    max_cost_usd: float | None = None,
    max_turns: int | None = None,
    is_sub_agent: bool = False,
    terminal_output: bool = False,
    custom_system_prompt: str | None = None,
    session_repository: SessionRepository | None = None,
    tool_registry: ToolRegistry | None = None,
    model_limits_resolver=None,
) -> FullAgentHarness:
    composition = build_agent_composition(
        FullProfile(system_prompt=custom_system_prompt),
        config=AgentConfig(
            permission_mode=permission_mode,
            model=model,
            api_base=api_base,
            anthropic_base_url=anthropic_base_url,
            api_key=api_key,
            thinking=thinking,
            max_cost_usd=max_cost_usd,
            max_turns=max_turns,
            is_sub_agent=is_sub_agent,
            terminal_output=terminal_output,
        ),
        bindings=RuntimeBindings(
            provider=ProviderBindings(
                provider_factory=_provider_factory,
                model_limits_resolver=model_limits_resolver,
            ),
            session=SessionBindings(
                session_repository=session_repository,
            ),
            tool=ToolBindings(
                tool_registry=tool_registry,
                pre_tool_use_hooks_loader=load_pre_tool_use_hooks,
            ),
            interaction=InteractionBindings(
                dynamic_system_context_builder=_dynamic_context_builder,
                terminal_renderer_factory=_terminal_renderer_factory,
                print_info=_print_info,
                print_error=_print_error,
                print_confirmation=_print_confirmation,
                print_sub_agent_start=_print_subagent_start,
                print_sub_agent_end=_print_subagent_end,
            ),
        ),
    )
    runtime = composition.runtime
    agent = MetaAgent(
        agent_runtime=runtime.agent,
        provider_controller=runtime.provider_controller,
        conversation=runtime.conversation,
        session=runtime.session,
        usage=runtime.usage,
        budget=runtime.budget,
        permission_mode=permission_mode,
    )
    return FullAgentHarness(composition=composition, agent=agent)


async def execute_tool(
    harness: FullAgentHarness,
    name: str,
    arguments: dict,
    tool_call_id: str = "",
) -> str:
    """真实工具执行路径：ToolRuntime.execute，返回结果文本。"""
    result = await harness.composition.tooling.runtime.execute(
        tool_call_id=tool_call_id,
        name=name,
        arguments=arguments,
    )
    return result.content
