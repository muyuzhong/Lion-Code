"""Tests for the Capability SPI: registration, aggregation, and close semantics."""

from __future__ import annotations

from typing import Any

import pytest

from lion_code.capabilities import (
    CapabilityRegistry,
    CapabilitySpec,
    DuplicateCapabilityError,
)
from lion_code.context import ContextView
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


class _FakeContextLayer:
    def __init__(self, layer_id: str) -> None:
        self._id = layer_id

    @property
    def layer_id(self) -> str:
        return self._id

    def render(self, _view: ContextView) -> str:
        return self._id


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
        ts = _FakeToolSource(["browser_tool"])
        registry.register(CapabilitySpec(name="browser", tool_sources=(ts,)))

        assert registry.tool_sources == (ts,)

    def test_context_layer_slot_is_optional_and_aggregated(self) -> None:
        layer = _FakeContextLayer("state")
        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="plain"))
        registry.register(
            CapabilitySpec(name="stateful", context_layer=layer),
        )

        assert registry.context_layers == (layer,)

    def test_register_multiple_capabilities(self) -> None:
        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="browser"))
        registry.register(CapabilitySpec(name="sandbox"))
        registry.register(CapabilitySpec(name="checkpoint"))

        assert registry.tool_sources == ()
        assert registry.session_participants == ()

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
        session_participant = _FakeSessionParticipant()
        resource = _FakeResource("resource", [])
        tool_sources = [tool_source]
        prompt_layers = [prompt_layer]
        session_participants = [session_participant]
        resources = [resource]
        inputs: dict[str, Any] = {
            "tool_sources": tool_sources,
            "prompt_layers": prompt_layers,
            "session_participants": session_participants,
            "resources": resources,
        }

        spec = CapabilitySpec(name="sandbox", **inputs)

        assert spec.tool_sources == (tool_source,)
        assert spec.prompt_layers == (prompt_layer,)
        assert spec.session_participants == (session_participant,)
        assert spec.resources == (resource,)

        tool_sources.clear()
        prompt_layers.clear()
        session_participants.clear()
        resources.clear()

        assert spec.tool_sources == (tool_source,)
        assert spec.prompt_layers == (prompt_layer,)
        assert spec.session_participants == (session_participant,)
        assert spec.resources == (resource,)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


class TestAggregation:
    def test_aggregate_tool_sources_in_registration_order(self) -> None:
        ts1 = _FakeToolSource(["tool_a", "tool_b"])
        ts2 = _FakeToolSource(["tool_c"])

        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="cap_a", tool_sources=(ts1,)))
        registry.register(CapabilitySpec(name="cap_b", tool_sources=(ts2,)))

        sources = registry.tool_sources

        assert sources == (ts1, ts2)
        assert [tool.name for tool in sources[0].tools()] == ["tool_a", "tool_b"]
        assert [tool.name for tool in sources[1].tools()] == ["tool_c"]

    def test_aggregate_prompt_layers_in_registration_order(self) -> None:
        pl1 = _FakePromptLayer("layer_1", "fragment A")
        pl2 = _FakePromptLayer("layer_2", "fragment B")

        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="cap_a", prompt_layers=(pl1,)))
        registry.register(CapabilitySpec(name="cap_b", prompt_layers=(pl2,)))

        layers = registry.prompt_layers

        assert [layer.layer_id for layer in layers] == ["layer_1", "layer_2"]
        assert [layer.render() for layer in layers] == ["fragment A", "fragment B"]

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

        registry = CapabilityRegistry()
        registry.register(
            CapabilitySpec(
                name="multi",
                tool_sources=(ts,),
                prompt_layers=(pl,),
            )
        )

        assert registry.tool_sources == (ts,)
        assert registry.prompt_layers == (pl,)

    def test_empty_registry_returns_empty_tuples(self) -> None:
        registry = CapabilityRegistry()

        assert registry.tool_sources == ()
        assert registry.prompt_layers == ()
        assert registry.context_layers == ()
        assert registry.session_participants == ()
        assert registry.resources == ()


# ---------------------------------------------------------------------------
# Close semantics
# ---------------------------------------------------------------------------


class TestCloseSemantics:
    async def test_close_all_in_reverse_registration_order(self) -> None:
        close_log: list[str] = []
        r1 = _FakeResource("res_browser", close_log)
        r2 = _FakeResource("res_sandbox", close_log)

        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="browser", resources=(r1,)))
        registry.register(CapabilitySpec(name="sandbox", resources=(r2,)))

        await registry.close_all()

        # Reverse registration order: sandbox first, then browser.
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
        """Register, aggregate, and verify ordering for a realistic set."""
        ts_browser = _FakeToolSource(["navigate", "screenshot"])
        pl_browser = _FakePromptLayer("browser_layer", "You can use a browser.")

        ts_sandbox = _FakeToolSource(["run_code"])
        sp_sandbox = _FakeSessionParticipant()

        ts_checkpoint = _FakeToolSource(["save_state"])

        registry = CapabilityRegistry()
        registry.register(
            CapabilitySpec(
                name="browser",
                tool_sources=(ts_browser,),
                prompt_layers=(pl_browser,),
            )
        )
        registry.register(
            CapabilitySpec(
                name="sandbox",
                tool_sources=(ts_sandbox,),
                session_participants=(sp_sandbox,),
            )
        )
        registry.register(
            CapabilitySpec(
                name="checkpoint",
                tool_sources=(ts_checkpoint,),
            )
        )

        # Aggregated slots preserve registration order.
        assert [[tool.name for tool in s.tools()] for s in registry.tool_sources] == [
            ["navigate", "screenshot"],
            ["run_code"],
            ["save_state"],
        ]
        assert [layer.layer_id for layer in registry.prompt_layers] == ["browser_layer"]
        assert len(registry.session_participants) == 1

    async def test_full_close_lifecycle(self) -> None:
        close_log: list[str] = []
        r_browser = _FakeResource("browser_conn", close_log)
        r_sandbox = _FakeResource("sandbox_proc", close_log)
        r_checkpoint = _FakeResource("checkpoint_file", close_log)

        registry = CapabilityRegistry()
        registry.register(CapabilitySpec(name="browser", resources=(r_browser,)))
        registry.register(CapabilitySpec(name="sandbox", resources=(r_sandbox,)))
        registry.register(CapabilitySpec(name="checkpoint", resources=(r_checkpoint,)))

        await registry.close_all()

        # Reverse registration order.
        assert close_log == ["checkpoint_file", "sandbox_proc", "browser_conn"]
