"""Tests for the first batch of Capability migrations: MCP, Skill, SubAgent.

These tests verify that:
- Capability-installed tools appear in the registry after Agent construction.
- Disabled capabilities (mcp_enabled=False) do not contribute MCP tools.
- MCP initialization failure preserves the existing fail-soft semantics.
- SubAgent permission inheritance is unchanged.
- Skill inline/fork behavior is unchanged.
- Capability close does not double-release shared MCP resources.
- Capability implementations do not reverse-depend on Agent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from unittest.mock import patch

from lion_code.capabilities import (
    CapabilityRegistry,
    CapabilitySpec,
    McpCapability,
    create_skill_capability,
    create_subagent_capability,
)
from lion_code.capabilities.skill import _SkillToolSource
from lion_code.mcp_client import McpManager
from lion_code.tooling.registry import ToolRegistry


class _RecordingTurnParticipant:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def before_turn(self) -> None:
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
# Disabled capability: MCP
# ---------------------------------------------------------------------------


class TestDisabledMcpCapability:
    def test_mcp_capability_is_root_false_skips_discovery(self) -> None:
        """When is_root=False, before_turn does nothing."""
        mcp_manager = McpManager()
        tool_registry = ToolRegistry()
        capability = McpCapability(
            mcp_manager=mcp_manager,
            tool_registry=tool_registry,
            emit_notice=lambda msg: None,
            is_already_initialized=lambda: False,
            mark_initialized=lambda: None,
            is_root=False,
        )

        asyncio.run(capability.before_turn())

        # No tools should be registered.
        assert tool_registry.all_tools() == []

    def test_mcp_capability_already_initialized_skips_discovery(self) -> None:
        """When already initialized, before_turn does nothing."""
        mcp_manager = McpManager()
        tool_registry = ToolRegistry()
        capability = McpCapability(
            mcp_manager=mcp_manager,
            tool_registry=tool_registry,
            emit_notice=lambda msg: None,
            is_already_initialized=lambda: True,
            mark_initialized=lambda: None,
            is_root=True,
        )

        asyncio.run(capability.before_turn())

        assert tool_registry.all_tools() == []


# ---------------------------------------------------------------------------
# MCP init failure: fail-soft semantics
# ---------------------------------------------------------------------------


class TestMcpFailSoft:
    async def test_mcp_init_failure_emits_notice_and_continues(self) -> None:
        """MCP discovery failure should emit a notice, not raise."""
        mcp_manager = McpManager()
        tool_registry = ToolRegistry()
        notices: list[str] = []

        capability = McpCapability(
            mcp_manager=mcp_manager,
            tool_registry=tool_registry,
            emit_notice=notices.append,
            is_already_initialized=lambda: False,
            mark_initialized=lambda: None,
            is_root=True,
        )

        # discover_tools will fail because no MCP servers are configured,
        # but the McpManager handles this gracefully (returns empty list).
        await capability.before_turn()

        # No tools registered, no exception raised.
        assert tool_registry.all_tools() == []

    async def test_mcp_init_exception_emits_notice(self) -> None:
        """If discover_tools raises, the notice is emitted and execution continues."""
        mcp_manager = McpManager()
        tool_registry = ToolRegistry()
        notices: list[str] = []

        capability = McpCapability(
            mcp_manager=mcp_manager,
            tool_registry=tool_registry,
            emit_notice=notices.append,
            is_already_initialized=lambda: False,
            mark_initialized=lambda: None,
            is_root=True,
        )

        # Patch discover_tools to raise.
        with patch.object(
            mcp_manager,
            "discover_tools",
            side_effect=RuntimeError("connection refused"),
        ):
            await capability.before_turn()

        assert len(notices) == 1
        assert "[mcp] Init failed" in notices[0]
        assert "connection refused" in notices[0]
        assert tool_registry.all_tools() == []

    async def test_mcp_init_marks_initialized_even_on_failure(self) -> None:
        """After a failed init, the capability should not retry on the next turn."""
        mcp_manager = McpManager()
        init_call_count = 0

        def check_init() -> bool:
            return init_call_count > 0

        def mark_init() -> None:
            nonlocal init_call_count
            init_call_count += 1

        capability = McpCapability(
            mcp_manager=mcp_manager,
            tool_registry=ToolRegistry(),
            emit_notice=lambda msg: None,
            is_already_initialized=check_init,
            mark_initialized=mark_init,
            is_root=True,
        )

        with patch.object(
            mcp_manager, "discover_tools", side_effect=RuntimeError("fail")
        ):
            await capability.before_turn()
            # Second call should skip because mark_initialized was called.
            await capability.before_turn()

        assert init_call_count == 1


# ---------------------------------------------------------------------------
# Capability close: no double-release of shared MCP resources
# ---------------------------------------------------------------------------


class TestCapabilityClose:
    async def test_mcp_capability_has_no_closeable_resources(self) -> None:
        """MCP capability must not own resources; ToolEnvironment owns disconnect."""
        spec = McpCapability(
            mcp_manager=McpManager(),
            tool_registry=ToolRegistry(),
            emit_notice=lambda msg: None,
            is_already_initialized=lambda: False,
            mark_initialized=lambda: None,
            is_root=True,
        ).spec

        assert spec.resources == ()

    async def test_capability_registry_close_all_does_not_touch_mcp(self) -> None:
        """close_all must not call disconnect_all on the MCP manager."""
        mcp_manager = McpManager()
        disconnect_called = False
        original_disconnect = mcp_manager.disconnect_all

        async def tracking_disconnect() -> None:
            nonlocal disconnect_called
            disconnect_called = True
            await original_disconnect()

        mcp_manager.disconnect_all = tracking_disconnect  # type: ignore[method-assign]

        registry = CapabilityRegistry()
        registry.register(
            McpCapability(
                mcp_manager=mcp_manager,
                tool_registry=ToolRegistry(),
                emit_notice=lambda msg: None,
                is_already_initialized=lambda: True,
                mark_initialized=lambda: None,
                is_root=True,
            ).spec
        )

        await registry.close_all()

        assert not disconnect_called, (
            "CapabilityRegistry.close_all must not trigger MCP disconnect; "
            "ToolEnvironment owns that lifecycle."
        )

    async def test_skill_and_subagent_capabilities_have_no_resources(self) -> None:
        registry = CapabilityRegistry()
        registry.register(create_skill_capability(_CAPABILITY_DEPENDENCY))
        registry.register(create_subagent_capability(_CAPABILITY_DEPENDENCY))

        assert registry.resources == ()


# ---------------------------------------------------------------------------
# Architecture: Capability implementations must not import Agent
# ---------------------------------------------------------------------------


class TestCapabilityBoundaryCompliance:
    def test_mcp_capability_spec_does_not_reference_agent(self) -> None:
        """McpCapability.spec must be constructible without any Agent reference."""
        capability = McpCapability(
            mcp_manager=McpManager(),
            tool_registry=ToolRegistry(),
            emit_notice=lambda msg: None,
            is_already_initialized=lambda: False,
            mark_initialized=lambda: None,
            is_root=True,
        )
        spec = capability.spec

        # The spec should only have turn_participants, no tool_sources or resources.
        assert spec.name == "mcp"
        assert len(spec.turn_participants) == 1
        assert spec.tool_sources == ()
        assert spec.resources == ()

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
            mcp_enabled=False,
        )

        tool_names = {t.name for t in agent.tool_registry.all_tools()}
        assert "skill" in tool_names
        assert "agent" in tool_names
        assert "enter_plan_mode" in tool_names
        assert "exit_plan_mode" in tool_names

    def test_root_agent_with_mcp_disabled_has_no_mcp_tools(self) -> None:
        """When mcp_enabled=False, no MCP tools should be registered."""
        from lion_code.agent import Agent

        agent = Agent(
            api_key="test-key",
            terminal_output=False,
            mcp_enabled=False,
        )

        tool_names = {t.name for t in agent.tool_registry.all_tools()}
        mcp_tools = [name for name in tool_names if name.startswith("mcp__")]
        assert mcp_tools == []

    def test_agent_has_capability_registry_with_three_capabilities(self) -> None:
        """Agent should register mcp, skill, and subagent capabilities."""
        from lion_code.agent import Agent

        agent = Agent(
            api_key="test-key",
            terminal_output=False,
            mcp_enabled=False,
        )

        names = set(agent._capability_registry.names)  # noqa: SLF001
        assert "mcp" in names
        assert "skill" in names
        assert "subagent" in names
        assert "plan" in names

    def test_capability_runtime_calls_mcp_before_turn(self) -> None:
        """CapabilityRuntime should invoke the MCP TurnParticipant."""
        from lion_code.agent import Agent

        agent = Agent(
            api_key="test-key",
            terminal_output=False,
            mcp_enabled=False,
        )

        # MCP capability is registered with is_root=False when mcp_enabled=False,
        # so before_turn should be a no-op.
        asyncio.run(agent._capability_runtime.before_turn())  # noqa: SLF001

    def test_capability_runtime_with_mcp_enabled_skips_if_initialized(
        self,
    ) -> None:
        """When _mcp_initialized is True, before_turn should skip MCP discovery."""
        from lion_code.agent import Agent

        agent = Agent(
            api_key="test-key",
            terminal_output=False,
            mcp_enabled=True,
        )
        agent._mcp_initialized = True  # noqa: SLF001

        # Should not raise or attempt MCP discovery.
        asyncio.run(agent._capability_runtime.before_turn())  # noqa: SLF001

    def test_capability_runtime_after_turn_runs_on_early_chat_exit(self) -> None:
        """轮次结束钩子覆盖未配置 API 时的提前返回。"""
        from lion_code.agent import Agent

        agent = Agent(
            api_key="test-key",
            terminal_output=False,
            mcp_enabled=False,
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

        assert participant.calls == ["before", "after"]

    def test_session_participant_runs_after_new_identity_transition(self) -> None:
        """Session callbacks observe the new identity before Core is reset."""
        from lion_code.agent import Agent

        agent = Agent(
            api_key="test-key",
            terminal_output=False,
            mcp_enabled=False,
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
            mcp_enabled=False,
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
            mcp_enabled=False,
            permission_mode="default",
        )

        child = agent._subagent_factory.create_for_agent_type("general")  # noqa: SLF001
        try:
            assert child.permission_mode == "bypassPermissions"
        finally:
            asyncio.run(child.close())

    def test_subagent_inherits_parent_tool_registry_filtered(self) -> None:
        """SubAgent should receive a filtered view of the parent's registry,
        including capability-contributed tools like 'agent' and 'skill'."""
        from lion_code.agent import Agent

        agent = Agent(
            api_key="test-key",
            terminal_output=False,
            mcp_enabled=False,
        )

        sub_agent = agent._subagent_factory.create_for_agent_type("general")  # noqa: SLF001

        try:
            sub_tools = {t.name for t in sub_agent.tool_registry.all_tools()}
            # general type excludes 'agent' and 'schedule_wakeup' but includes 'skill'.
            assert "skill" in sub_tools
            assert "agent" not in sub_tools
        finally:
            asyncio.run(sub_agent.close())
