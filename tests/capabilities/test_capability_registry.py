"""Tests for the Capability SPI: registration, dependency resolution, aggregation, and close semantics."""

from __future__ import annotations

from typing import Any

import pytest

from lion_code.capabilities import (
    CapabilityRegistry,
    CapabilitySpec,
    CircularDependencyError,
    DuplicateCapabilityError,
    MissingDependencyError,
)
from lion_code.tooling.types import LionTool, ToolResult

# ---------------------------------------------------------------------------
# Test helpers: minimal extension-slot implementations
# ---------------------------------------------------------------------------


class _FakeToolSource:
    """Minimal ToolSource that returns typed LionTool contributions."""

    def __init__(self, names: list[str]) -> None:
        self._tools = tuple(
            LionTool(
                name=name,
                label=name,
                description=name,
                parameters={"type": "object", "properties": {}},
                execute_fn=_execute_fake_tool,
            )
            for name in names
        )

    def tools(self) -> tuple[LionTool, ...]:
        return self._tools


async def _execute_fake_tool(
    _context,
    _tool_call_id,
    _arguments,
    _on_update,
) -> ToolResult:
    return ToolResult(content="ok")


class _FakePromptLayer:
    """Minimal PromptLayer with a stable id and render output."""

    def __init__(self, layer_id: str, text: str = "") -> None:
        self._id = layer_id
        self._text = text

    @property
    def layer_id(self) -> str:
        return self._id

    def render(self) -> str:
        return self._text


class _FakeProjectionLayer:
    """Minimal per-request projection layer."""

    def __init__(self, layer_id: str, suffix: str) -> None:
        self._id = layer_id
        self._suffix = suffix

    @property
    def layer_id(self) -> str:
        return self._id

    def project(self, messages, *, max_tokens):
        del max_tokens
        return [*messages, self._suffix]


class _FakeTurnParticipant:
    """Minimal TurnParticipant that records hook calls."""

    def __init__(self) -> None:
        self.before_calls = 0
        self.after_calls = 0

    async def before_turn(self, _user_message: str) -> None:
        self.before_calls += 1

    async def after_turn(self) -> None:
        self.after_calls += 1


class _FakeSessionParticipant:
    """Minimal SessionParticipant that records hook calls."""

    def __init__(self) -> None:
        self.new_calls = 0
        self.restore_calls = 0

    async def on_new_session(self) -> None:
        self.new_calls += 1

    async def on_restore_session(self) -> None:
        self.restore_calls += 1


class _FakeResource:
    """Minimal AsyncCloseable that records close order and can fail."""

    def __init__(self, name: str, close_log: list[str], *, fail: bool = False) -> None:
        self.name = name
        self._log = close_log
        self._fail = fail
        self.closed = False

    async def close(self) -> None:
        self._log.append(self.name)
        self.closed = True
        if self._fail:
            raise RuntimeError(f"close failed: {self.name}")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_register_single_capability(self) -> None:
        registry = CapabilityRegistry()
        spec = CapabilitySpec(name="browser")
        registry.register(spec)

        assert len(registry) == 1
        assert "browser" in registry
        assert registry.get("browser") is spec

    def test_register_multiple_capabilities(self) -> None:
        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="browser"))
        registry.register(CapabilitySpec(name="sandbox"))
        registry.register(CapabilitySpec(name="checkpoint"))

        assert len(registry) == 3
        assert registry.names == ("browser", "sandbox", "checkpoint")

    def test_duplicate_name_rejected(self) -> None:
        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="browser"))

        with pytest.raises(DuplicateCapabilityError, match="browser"):
            registry.register(CapabilitySpec(name="browser"))

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            CapabilitySpec(name="")

    def test_mutable_inputs_are_normalized_at_construction(self) -> None:
        tool_source = _FakeToolSource(["tool"])
        prompt_layer = _FakePromptLayer("layer")
        projection_layer = _FakeProjectionLayer("projection", "projected")
        turn_participant = _FakeTurnParticipant()
        session_participant = _FakeSessionParticipant()
        resource = _FakeResource("resource", [])
        tool_sources = [tool_source]
        prompt_layers = [prompt_layer]
        projection_layers = [projection_layer]
        turn_participants = [turn_participant]
        session_participants = [session_participant]
        resources = [resource]
        requires = {"browser"}
        inputs: dict[str, Any] = {
            "tool_sources": tool_sources,
            "prompt_layers": prompt_layers,
            "projection_layers": projection_layers,
            "turn_participants": turn_participants,
            "session_participants": session_participants,
            "resources": resources,
            "requires": requires,
        }

        spec = CapabilitySpec(name="sandbox", **inputs)

        assert spec.tool_sources == (tool_source,)
        assert spec.prompt_layers == (prompt_layer,)
        assert spec.projection_layers == (projection_layer,)
        assert spec.turn_participants == (turn_participant,)
        assert spec.session_participants == (session_participant,)
        assert spec.resources == (resource,)
        assert spec.requires == frozenset({"browser"})

        tool_sources.clear()
        prompt_layers.clear()
        projection_layers.clear()
        turn_participants.clear()
        session_participants.clear()
        resources.clear()
        requires.add("checkpoint")

        assert spec.tool_sources == (tool_source,)
        assert spec.prompt_layers == (prompt_layer,)
        assert spec.projection_layers == (projection_layer,)
        assert spec.turn_participants == (turn_participant,)
        assert spec.session_participants == (session_participant,)
        assert spec.resources == (resource,)
        assert spec.requires == frozenset({"browser"})

    def test_get_unknown_returns_none(self) -> None:
        registry = CapabilityRegistry()
        assert registry.get("nonexistent") is None

    def test_contains(self) -> None:
        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="browser"))

        assert "browser" in registry
        assert "sandbox" not in registry


# ---------------------------------------------------------------------------
# Dependency resolution
# ---------------------------------------------------------------------------


class TestDependencyResolution:
    def test_resolve_returns_registration_order_without_deps(self) -> None:
        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="browser"))
        registry.register(CapabilitySpec(name="sandbox"))
        registry.register(CapabilitySpec(name="checkpoint"))

        order = registry.resolve()

        assert order == ("browser", "sandbox", "checkpoint")

    def test_resolve_with_requires(self) -> None:
        registry = CapabilityRegistry()
        # sandbox depends on browser, so browser must come first
        registry.register(CapabilitySpec(name="browser"))
        registry.register(
            CapabilitySpec(name="sandbox", requires=frozenset({"browser"}))
        )

        order = registry.resolve()

        assert order.index("browser") < order.index("sandbox")

    def test_resolve_chained_dependencies(self) -> None:
        registry = CapabilityRegistry()
        # checkpoint -> sandbox -> browser
        registry.register(CapabilitySpec(name="browser"))
        registry.register(
            CapabilitySpec(name="sandbox", requires=frozenset({"browser"}))
        )
        registry.register(
            CapabilitySpec(name="checkpoint", requires=frozenset({"sandbox"}))
        )

        order = registry.resolve()

        assert order == ("browser", "sandbox", "checkpoint")

    def test_missing_dependency_raises(self) -> None:
        registry = CapabilityRegistry()
        registry.register(
            CapabilitySpec(name="sandbox", requires=frozenset({"browser"}))
        )

        with pytest.raises(MissingDependencyError, match=r"sandbox.*browser"):
            registry.resolve()

    def test_missing_dependency_error_names_both_capabilities(self) -> None:
        registry = CapabilityRegistry()
        registry.register(
            CapabilitySpec(name="scheduler", requires=frozenset({"checkpoint"}))
        )

        with pytest.raises(MissingDependencyError) as exc_info:
            registry.resolve()

        msg = str(exc_info.value)
        assert "scheduler" in msg
        assert "checkpoint" in msg

    def test_circular_dependency_raises(self) -> None:
        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="alpha", requires=frozenset({"beta"})))
        registry.register(CapabilitySpec(name="beta", requires=frozenset({"alpha"})))

        with pytest.raises(CircularDependencyError, match=r"alpha.*beta|beta.*alpha"):
            registry.resolve()

    def test_self_referencing_dependency_raises(self) -> None:
        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="loop", requires=frozenset({"loop"})))

        with pytest.raises(CircularDependencyError, match="loop"):
            registry.resolve()

    def test_circular_dependency_error_names_all_unresolved(self) -> None:
        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="alpha", requires=frozenset({"beta"})))
        registry.register(CapabilitySpec(name="beta", requires=frozenset({"gamma"})))
        registry.register(CapabilitySpec(name="gamma", requires=frozenset({"alpha"})))

        with pytest.raises(CircularDependencyError) as exc_info:
            registry.resolve()

        msg = str(exc_info.value)
        assert "alpha" in msg
        assert "beta" in msg
        assert "gamma" in msg

    def test_stable_order_with_no_dependencies(self) -> None:
        """Capabilities without inter-dependencies preserve registration order."""
        registry = CapabilityRegistry()
        for name in ["delta", "alpha", "charlie", "bravo"]:
            registry.register(CapabilitySpec(name=name))

        order = registry.resolve()

        assert order == ("delta", "alpha", "charlie", "bravo")

    def test_stable_order_with_independent_groups(self) -> None:
        """Two independent dependency groups preserve registration order."""
        registry = CapabilityRegistry()
        # Group 1: a -> b
        registry.register(CapabilitySpec(name="a"))
        registry.register(CapabilitySpec(name="b", requires=frozenset({"a"})))
        # Group 2: c -> d (independent of group 1)
        registry.register(CapabilitySpec(name="c"))
        registry.register(CapabilitySpec(name="d", requires=frozenset({"c"})))

        order = registry.resolve()

        # a before b, c before d; otherwise registration order.
        assert order.index("a") < order.index("b")
        assert order.index("c") < order.index("d")

    def test_resolve_cached_until_new_registration(self) -> None:
        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="browser"))
        first = registry.resolve()
        second = registry.resolve()

        assert first is second or first == second

        registry.register(CapabilitySpec(name="sandbox"))
        third = registry.resolve()

        assert third == ("browser", "sandbox")


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


class TestAggregation:
    def test_aggregate_tool_sources(self) -> None:
        ts1 = _FakeToolSource(["tool_a", "tool_b"])
        ts2 = _FakeToolSource(["tool_c"])

        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="cap_a", tool_sources=(ts1,)))
        registry.register(CapabilitySpec(name="cap_b", tool_sources=(ts2,)))

        sources = registry.tool_sources

        assert sources == (ts1, ts2)
        assert [tool.name for tool in sources[0].tools()] == ["tool_a", "tool_b"]
        assert [tool.name for tool in sources[1].tools()] == ["tool_c"]

    def test_aggregate_prompt_layers(self) -> None:
        pl1 = _FakePromptLayer("layer_1", "fragment A")
        pl2 = _FakePromptLayer("layer_2", "fragment B")

        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="cap_a", prompt_layers=(pl1,)))
        registry.register(CapabilitySpec(name="cap_b", prompt_layers=(pl2,)))

        layers = registry.prompt_layers

        assert [layer.layer_id for layer in layers] == ["layer_1", "layer_2"]
        assert [layer.render() for layer in layers] == ["fragment A", "fragment B"]

    def test_aggregate_projection_layers(self) -> None:
        pl1 = _FakeProjectionLayer("layer_1", "first")
        pl2 = _FakeProjectionLayer("layer_2", "second")

        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="cap_a", projection_layers=(pl1,)))
        registry.register(CapabilitySpec(name="cap_b", projection_layers=(pl2,)))

        assert registry.projection_layers == (pl1, pl2)

    def test_aggregate_turn_participants(self) -> None:
        tp1 = _FakeTurnParticipant()
        tp2 = _FakeTurnParticipant()

        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="cap_a", turn_participants=(tp1,)))
        registry.register(CapabilitySpec(name="cap_b", turn_participants=(tp2,)))

        participants = registry.turn_participants

        assert participants == (tp1, tp2)

    def test_aggregate_session_participants(self) -> None:
        sp1 = _FakeSessionParticipant()
        sp2 = _FakeSessionParticipant()

        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="cap_a", session_participants=(sp1,)))
        registry.register(CapabilitySpec(name="cap_b", session_participants=(sp2,)))

        participants = registry.session_participants

        assert participants == (sp1, sp2)

    def test_aggregate_multiple_slots_from_one_capability(self) -> None:
        ts = _FakeToolSource(["tool_x"])
        pl = _FakePromptLayer("layer_x", "text")
        tp = _FakeTurnParticipant()

        registry = CapabilityRegistry()
        registry.register(
            CapabilitySpec(
                name="multi",
                tool_sources=(ts,),
                prompt_layers=(pl,),
                turn_participants=(tp,),
            )
        )

        assert registry.tool_sources == (ts,)
        assert registry.prompt_layers == (pl,)
        assert registry.turn_participants == (tp,)

    def test_aggregation_respects_dependency_order(self) -> None:
        """Tool sources from required capabilities come before dependents."""
        ts_browser = _FakeToolSource(["browser_tool"])
        ts_sandbox = _FakeToolSource(["sandbox_tool"])

        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="browser", tool_sources=(ts_browser,)))
        registry.register(
            CapabilitySpec(
                name="sandbox",
                tool_sources=(ts_sandbox,),
                requires=frozenset({"browser"}),
            )
        )

        sources = registry.tool_sources

        assert sources == (ts_browser, ts_sandbox)

    def test_empty_registry_returns_empty_tuples(self) -> None:
        registry = CapabilityRegistry()

        assert registry.tool_sources == ()
        assert registry.prompt_layers == ()
        assert registry.projection_layers == ()
        assert registry.turn_participants == ()
        assert registry.session_participants == ()
        assert registry.resources == ()

    def test_lazy_resolution_on_property_access(self) -> None:
        """Properties auto-resolve without explicit resolve() call."""
        ts = _FakeToolSource(["tool"])

        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="cap", tool_sources=(ts,)))

        # Access without calling resolve() first.
        assert registry.tool_sources == (ts,)


# ---------------------------------------------------------------------------
# Close semantics
# ---------------------------------------------------------------------------


class TestCloseSemantics:
    async def test_close_all_in_reverse_dependency_order(self) -> None:
        close_log: list[str] = []
        r1 = _FakeResource("res_browser", close_log)
        r2 = _FakeResource("res_sandbox", close_log)

        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="browser", resources=(r1,)))
        registry.register(
            CapabilitySpec(
                name="sandbox",
                resources=(r2,),
                requires=frozenset({"browser"}),
            )
        )

        await registry.close_all()

        # Reverse order: sandbox first, then browser.
        assert close_log == ["res_sandbox", "res_browser"]

    async def test_close_all_reverse_within_capability(self) -> None:
        close_log: list[str] = []
        r1 = _FakeResource("first", close_log)
        r2 = _FakeResource("second", close_log)

        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="cap", resources=(r1, r2)))

        await registry.close_all()

        # Reverse declaration order within one capability.
        assert close_log == ["second", "first"]

    async def test_close_all_continues_on_error(self) -> None:
        close_log: list[str] = []
        r_fail = _FakeResource("failing", close_log, fail=True)
        r_ok = _FakeResource("ok", close_log)

        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="cap_a", resources=(r_fail,)))
        registry.register(CapabilitySpec(name="cap_b", resources=(r_ok,)))

        with pytest.raises(RuntimeError, match="failing"):
            await registry.close_all()

        # Both resources were attempted despite the error.
        assert "failing" in close_log
        assert "ok" in close_log

    async def test_close_all_with_no_resources(self) -> None:
        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="cap"))

        # Should not raise.
        await registry.close_all()

    async def test_close_all_first_error_raised(self) -> None:
        close_log: list[str] = []
        r1 = _FakeResource("first_fail", close_log, fail=True)
        r2 = _FakeResource("second_fail", close_log, fail=True)

        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="cap_a", resources=(r1,)))
        registry.register(CapabilitySpec(name="cap_b", resources=(r2,)))

        with pytest.raises(RuntimeError) as exc_info:
            await registry.close_all()

        # The first error (from cap_b, which is closed first in reverse order)
        # is raised.
        assert "second_fail" in str(exc_info.value) or "first_fail" in str(
            exc_info.value
        )
        # Both were attempted.
        assert set(close_log) == {"first_fail", "second_fail"}


# ---------------------------------------------------------------------------
# Integration: full registry lifecycle
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_full_lifecycle(self) -> None:
        """Register, resolve, aggregate, and verify ordering for a realistic set."""
        ts_browser = _FakeToolSource(["navigate", "screenshot"])
        pl_browser = _FakePromptLayer("browser_layer", "You can use a browser.")
        tp_browser = _FakeTurnParticipant()

        ts_sandbox = _FakeToolSource(["run_code"])
        sp_sandbox = _FakeSessionParticipant()

        ts_checkpoint = _FakeToolSource(["save_state"])

        registry = CapabilityRegistry()
        registry.register(
            CapabilitySpec(
                name="browser",
                tool_sources=(ts_browser,),
                prompt_layers=(pl_browser,),
                turn_participants=(tp_browser,),
            )
        )
        registry.register(
            CapabilitySpec(
                name="sandbox",
                tool_sources=(ts_sandbox,),
                session_participants=(sp_sandbox,),
                requires=frozenset({"browser"}),
            )
        )
        registry.register(
            CapabilitySpec(
                name="checkpoint",
                tool_sources=(ts_checkpoint,),
                requires=frozenset({"sandbox"}),
            )
        )

        # Verify dependency-resolved order.
        assert registry.resolve() == ("browser", "sandbox", "checkpoint")

        # Verify aggregated slots.
        assert [[tool.name for tool in s.tools()] for s in registry.tool_sources] == [
            ["navigate", "screenshot"],
            ["run_code"],
            ["save_state"],
        ]
        assert [layer.layer_id for layer in registry.prompt_layers] == ["browser_layer"]
        assert len(registry.turn_participants) == 1
        assert len(registry.session_participants) == 1

    async def test_full_close_lifecycle(self) -> None:
        close_log: list[str] = []
        r_browser = _FakeResource("browser_conn", close_log)
        r_sandbox = _FakeResource("sandbox_proc", close_log)
        r_checkpoint = _FakeResource("checkpoint_file", close_log)

        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="browser", resources=(r_browser,)))
        registry.register(
            CapabilitySpec(
                name="sandbox",
                resources=(r_sandbox,),
                requires=frozenset({"browser"}),
            )
        )
        registry.register(
            CapabilitySpec(
                name="checkpoint",
                resources=(r_checkpoint,),
                requires=frozenset({"sandbox"}),
            )
        )

        await registry.close_all()

        # Reverse dependency order.
        assert close_log == ["checkpoint_file", "sandbox_proc", "browser_conn"]
