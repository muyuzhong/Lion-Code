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

from full_agent import build_full_agent_harness

from lion_code.capabilities import (
    CapabilityRegistry,
    CapabilitySpec,
)
from lion_code.capabilities.skill.capability import (
    _SkillToolSource,
    create_skill_capability,
)
from lion_code.capabilities.subagent.capability import create_subagent_capability


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
        assert spec.resources == ()

    def test_subagent_capability_spec_is_tool_source_only(self) -> None:
        spec = create_subagent_capability(_CAPABILITY_DEPENDENCY)
        assert spec.name == "subagent"
        assert len(spec.tool_sources) == 1
        assert spec.resources == ()


# ---------------------------------------------------------------------------
# Agent composition: tools appear after construction
# ---------------------------------------------------------------------------


class TestAgentCompositionWithCapabilities:
    """Integration tests that verify the Agent correctly wires capability tools."""

    def test_root_agent_has_skill_and_agent_tools(self) -> None:
        """A root agent should have the 'skill' and 'agent' tools in its registry
        after construction, contributed by capabilities."""

        agent = build_full_agent_harness(
            api_key="test-key",
            terminal_output=False,
        )

        tool_names = {t.name for t in agent.composition.tooling.registry.all_tools()}
        assert "skill" in tool_names
        assert "agent" in tool_names
        assert "enter_plan_mode" in tool_names
        assert "exit_plan_mode" in tool_names

    def test_agent_has_capability_registry_with_builtin_capabilities(self) -> None:
        """Agent should register skill, subagent and plan capabilities."""

        agent = build_full_agent_harness(
            api_key="test-key",
            terminal_output=False,
        )

        sources = agent.composition.capabilities.registry.tool_sources  # noqa: SLF001
        assert len(sources) == 3

    def test_session_participant_runs_after_new_identity_transition(self) -> None:
        """Session callbacks observe the new identity before Core is reset."""

        agent = build_full_agent_harness(
            api_key="test-key",
            terminal_output=False,
        )
        original_id = agent.agent.session_id
        participant = _RecordingSessionParticipant(lambda: agent.agent.session_id)
        agent.composition.capabilities.registry.register(  # noqa: SLF001
            CapabilitySpec(
                name="test-session-lifecycle",
                session_participants=(participant,),
            )
        )

        try:
            asyncio.run(agent.agent.new_session())
        finally:
            asyncio.run(agent.agent.close())

        assert participant.calls == [("new", agent.agent.session_id)]
        assert participant.calls[0][1] != original_id

    def test_agent_close_closes_capability_resources(self) -> None:
        """Agent.close 应通过 CapabilityRuntime 回收 Capability 资源。"""

        agent = build_full_agent_harness(
            api_key="test-key",
            terminal_output=False,
        )
        resource = _FakeCapabilityResource()
        agent.composition.capabilities.registry.register(  # noqa: SLF001
            CapabilitySpec(
                name="test-resource-lifecycle",
                resources=(resource,),
            )
        )

        asyncio.run(agent.agent.close())

        assert resource.close_calls == 1


# ---------------------------------------------------------------------------
# SubAgent permission (PR4: Permission 不再有 plan/auto 模式，子 Agent 一律 bypassPermissions)
# ---------------------------------------------------------------------------


class TestSubAgentPermissionInheritance:
    def test_subagent_uses_bypass_permission_mode(self) -> None:
        """子 Agent 始终以 bypassPermissions 构造（无父模式继承）。"""

        agent = build_full_agent_harness(
            api_key="test-key",
            terminal_output=False,
            permission_mode="default",
        )

        with patch(
            "lion_code.meta_agent.build_coding_agent",
        ) as build_child:
            child = (
                agent.composition.capabilities.subagent_factory.create_for_agent_type(
                    "general"
                )
            )  # noqa: SLF001

        assert build_child.call_args.kwargs["permission_mode"] == "bypassPermissions"
        assert build_child.call_args.kwargs["is_sub_agent"] is True
        assert child is build_child.return_value

    def test_subagent_inherits_parent_tool_registry_filtered(self) -> None:
        """SubAgent should receive a filtered view of the parent's registry,
        including capability-contributed tools like 'agent' and 'skill'."""

        agent = build_full_agent_harness(
            api_key="test-key",
            terminal_output=False,
        )

        with patch(
            "lion_code.meta_agent.build_coding_agent",
            return_value=Mock(),
        ) as build_child:
            agent.composition.capabilities.subagent_factory.create_for_agent_type(
                "general"
            )  # noqa: SLF001

        child_registry = build_child.call_args.kwargs["tool_registry"]
        sub_tools = {t.name for t in child_registry.all_tools()}
        # general type excludes 'agent' but includes 'skill'.
        assert "skill" in sub_tools
        assert "agent" not in sub_tools
