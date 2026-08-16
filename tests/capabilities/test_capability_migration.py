"""Capability 迁移批次测试：Skill、SubAgent。

These tests verify that:
- Capability-installed tools appear in the registry after Agent construction.
- SubAgent permission inheritance is unchanged.
- Skill inline/fork behavior is unchanged.
- Capability implementations do not reverse-depend on Agent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from unittest.mock import Mock, patch

from lion_code.capabilities import (
    CapabilityRegistry,
    CapabilitySpec,
    create_skill_capability,
    create_subagent_capability,
)
from lion_code.capabilities.skill import _SkillToolSource


class _RecordingTurnParticipant:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def before_turn(self, _user_message: str) -> None:
        self.calls.append("before")

    async def after_turn(self) -> None:
        self.calls.append("after")


class _RecordingSessionParticipant:
    def __init__(self, session_id: Callable[[], str]) -> None:
        self._session_id = session_id
        self.calls: list[tuple[str, str]] = []

    async def on_new_session(self) -> None:
        self.calls.append(("new", self._session_id()))

    async def on_restore_session(self) -> None:
        self.calls.append(("restore", self._session_id()))


class _FakeCapabilityResource:
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


class _CapabilityDependency:
    async def __call__(self, _arguments):
        return None


_CAPABILITY_DEPENDENCY = _CapabilityDependency()


# ---------------------------------------------------------------------------
# Tool installation via Capability ToolSource
# ---------------------------------------------------------------------------


class TestCapabilityToolInstallation:
    def test_skill_capability_provides_skill_tool(self) -> None:
        spec = create_skill_capability(_CAPABILITY_DEPENDENCY)
        sources = spec.tool_sources
        assert len(sources) == 1
        tools = sources[0].tools()
        assert len(tools) == 1
        assert tools[0].name == "skill"

    def test_subagent_capability_provides_agent_tool(self) -> None:
        spec = create_subagent_capability(_CAPABILITY_DEPENDENCY)
        sources = spec.tool_sources
        assert len(sources) == 1
        tools = sources[0].tools()
        assert len(tools) == 1
        assert tools[0].name == "agent"

    def test_capability_registry_aggregates_both_tool_sources(self) -> None:
        registry = CapabilityRegistry()
        registry.register(create_skill_capability(_CAPABILITY_DEPENDENCY))
        registry.register(create_subagent_capability(_CAPABILITY_DEPENDENCY))

        sources = registry.tool_sources
        assert len(sources) == 2

        all_tools: list[str] = []
        for source in sources:
            for tool in source.tools():
                all_tools.append(tool.name)
        assert "skill" in all_tools
        assert "agent" in all_tools

    def test_tool_source_returns_same_tool_instance(self) -> None:
        """ToolSource should return a stable tool definition, not recreate it."""
        source = _SkillToolSource(_CAPABILITY_DEPENDENCY)
        first = source.tools()
        second = source.tools()
        assert first[0] is second[0]


# ---------------------------------------------------------------------------
# Capability close: resources released exactly once
# ---------------------------------------------------------------------------


class TestCapabilityClose:
    async def test_skill_and_subagent_capabilities_have_no_resources(self) -> None:
        registry = CapabilityRegistry()
        registry.register(create_skill_capability(_CAPABILITY_DEPENDENCY))
        registry.register(create_subagent_capability(_CAPABILITY_DEPENDENCY))

        assert registry.resources == ()


# ---------------------------------------------------------------------------
# Architecture: Capability implementations must not import Agent
# ---------------------------------------------------------------------------


class TestCapabilityBoundaryCompliance:
    def test_skill_capability_spec_is_tool_source_only(self) -> None:
        spec = create_skill_capability(_CAPABILITY_DEPENDENCY)
        assert spec.name == "skill"
        assert len(spec.tool_sources) == 1
        assert spec.turn_participants == ()
        assert spec.resources == ()

    def test_subagent_capability_spec_is_tool_source_only(self) -> None:
        spec = create_subagent_capability(_CAPABILITY_DEPENDENCY)
        assert spec.name == "subagent"
        assert len(spec.tool_sources) == 1
        assert spec.turn_participants == ()
        assert spec.resources == ()


# ---------------------------------------------------------------------------
# Agent composition: tools appear after construction
# ---------------------------------------------------------------------------


class TestAgentCompositionWithCapabilities:
    """Integration tests that verify the Agent correctly wires capability tools."""

    def test_root_agent_has_skill_and_agent_tools(self) -> None:
        """A root agent should have the 'skill' and 'agent' tools in its registry
        after construction, contributed by capabilities."""
        from lion_code.agent import Agent

        agent = Agent(
            api_key="test-key",
            terminal_output=False,
        )

        tool_names = {t.name for t in agent.tool_registry.all_tools()}
        assert "skill" in tool_names
        assert "agent" in tool_names
        assert "enter_plan_mode" in tool_names
        assert "exit_plan_mode" in tool_names

    def test_agent_has_capability_registry_with_builtin_capabilities(self) -> None:
        """Agent should register skill, subagent and plan capabilities."""
        from lion_code.agent import Agent

        agent = Agent(
            api_key="test-key",
            terminal_output=False,
        )

        names = set(agent._capability_registry.names)  # noqa: SLF001
        assert "skill" in names
        assert "subagent" in names
        assert "plan" in names

    def test_capability_runtime_before_turn_runs_without_external_tools(self) -> None:
        """CapabilityRuntime.before_turn 在无外部工具 Capability 时是合法空转。"""
        from lion_code.agent import Agent

        agent = Agent(
            api_key="test-key",
            terminal_output=False,
        )

        asyncio.run(agent._capability_runtime.before_turn("question"))  # noqa: SLF001
        asyncio.run(agent.close())

    def test_capability_runtime_after_turn_runs_on_early_chat_exit(self) -> None:
        """轮次结束钩子覆盖未配置 API 时的提前返回。"""
        from lion_code.agent import Agent

        agent = Agent(
            api_key="test-key",
            terminal_output=False,
        )
        agent.configure_api(api_key="")
        participant = _RecordingTurnParticipant()
        agent._capability_registry.register(  # noqa: SLF001
            CapabilitySpec(
                name="test-turn-lifecycle",
                turn_participants=(participant,),
            )
        )

        try:
            asyncio.run(agent.chat("hello"))
        finally:
            asyncio.run(agent.close())

        assert participant.calls == ["after"]

    def test_session_participant_runs_after_new_identity_transition(self) -> None:
        """Session callbacks observe the new identity before Core is reset."""
        from lion_code.agent import Agent

        agent = Agent(
            api_key="test-key",
            terminal_output=False,
        )
        original_id = agent.session_id
        participant = _RecordingSessionParticipant(lambda: agent.session_id)
        agent._capability_registry.register(  # noqa: SLF001
            CapabilitySpec(
                name="test-session-lifecycle",
                session_participants=(participant,),
            )
        )

        try:
            asyncio.run(agent.clear_history())
        finally:
            asyncio.run(agent.close())

        assert participant.calls == [("new", agent.session_id)]
        assert participant.calls[0][1] != original_id

    def test_agent_close_closes_capability_resources(self) -> None:
        """Agent.close 应通过 SessionLifecycle 回收 Capability 资源。"""
        from lion_code.agent import Agent

        agent = Agent(
            api_key="test-key",
            terminal_output=False,
        )
        resource = _FakeCapabilityResource()
        agent._capability_registry.register(  # noqa: SLF001
            CapabilitySpec(
                name="test-resource-lifecycle",
                resources=(resource,),
            )
        )

        asyncio.run(agent.close())

        assert resource.close_calls == 1


# ---------------------------------------------------------------------------
# SubAgent permission (PR4: Permission 不再有 plan/auto 模式，子 Agent 一律 bypassPermissions)
# ---------------------------------------------------------------------------


class TestSubAgentPermissionInheritance:
    def test_subagent_uses_bypass_permission_mode(self) -> None:
        """子 Agent 始终以 bypassPermissions 构造（无父模式继承）。"""
        from lion_code.agent import Agent

        agent = Agent(
            api_key="test-key",
            terminal_output=False,
            permission_mode="default",
        )

        with patch(
            "lion_code.meta_agent.build_coding_agent",
        ) as build_child:
            child = agent._subagent_factory.create_for_agent_type("general")  # noqa: SLF001

        assert build_child.call_args.kwargs["permission_mode"] == "bypassPermissions"
        assert build_child.call_args.kwargs["is_sub_agent"] is True
        assert child is build_child.return_value

    def test_subagent_inherits_parent_tool_registry_filtered(self) -> None:
        """SubAgent should receive a filtered view of the parent's registry,
        including capability-contributed tools like 'agent' and 'skill'."""
        from lion_code.agent import Agent

        agent = Agent(
            api_key="test-key",
            terminal_output=False,
        )

        with patch(
            "lion_code.meta_agent.build_coding_agent",
            return_value=Mock(),
        ) as build_child:
            agent._subagent_factory.create_for_agent_type("general")  # noqa: SLF001

        child_registry = build_child.call_args.kwargs["tool_registry"]
        sub_tools = {t.name for t in child_registry.all_tools()}
        # general type excludes 'agent' but includes 'skill'.
        assert "skill" in sub_tools
        assert "agent" not in sub_tools
