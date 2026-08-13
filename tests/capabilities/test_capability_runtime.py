from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import pytest

from lion_code.capabilities import (
    CapabilityRegistry,
    CapabilityRuntime,
    CapabilitySpec,
)
from lion_code.tooling.types import JSONValue, LionTool, ToolResult


class _FullCapability:
    layer_id = "full"

    def __init__(self, events: list[str], name: str = "full") -> None:
        self._events = events
        self._name = name

    def tools(self) -> tuple[LionTool, ...]:
        async def execute(
            _context,
            _tool_call_id: str,
            _arguments: Mapping[str, JSONValue],
            _on_update,
        ) -> ToolResult:
            self._events.append(f"{self._name}:tool")
            return ToolResult(content="tool result")

        return (
            LionTool(
                name=f"{self._name}_tool",
                label=self._name,
                description="test capability tool",
                parameters={"type": "object"},
                execute_fn=execute,
            ),
        )

    def render(self) -> str:
        self._events.append(f"{self._name}:render")
        return f"{self._name} prompt"

    async def before_turn(self) -> None:
        self._events.append(f"{self._name}:before")

    async def after_turn(self) -> None:
        self._events.append(f"{self._name}:after")

    async def on_new_session(self) -> None:
        self._events.append(f"{self._name}:new")

    async def on_restore_session(self) -> None:
        self._events.append(f"{self._name}:restore")

    async def close(self) -> None:
        self._events.append(f"{self._name}:close")


def _full_spec(
    capability: _FullCapability, *, requires: frozenset[str] = frozenset()
) -> CapabilitySpec:
    return CapabilitySpec(
        name=capability._name,
        tool_sources=(capability,),
        prompt_layers=(capability,),
        turn_participants=(capability,),
        session_participants=(capability,),
        resources=(capability,),
        requires=requires,
    )


@pytest.mark.asyncio
async def test_full_spi_capability_contributes_and_dispatches_all_slots() -> None:
    events: list[str] = []
    capability = _FullCapability(events)
    registry = CapabilityRegistry()
    registry.register(_full_spec(capability))
    lifecycle = CapabilityRuntime(registry)

    assert [
        tool.name for source in registry.tool_sources for tool in source.tools()
    ] == ["full_tool"]
    assert registry.prompt_layers[0].render() == "full prompt"

    await lifecycle.on_new_session()
    await lifecycle.on_restore_session()
    await lifecycle.before_turn()
    await lifecycle.after_turn()
    result = (
        await registry.tool_sources[0]
        .tools()[0]
        .execute(cast(Any, None), "call", {}, None)
    )
    await lifecycle.close()
    await lifecycle.close()

    assert result.content == "tool result"
    assert events == [
        "full:render",
        "full:new",
        "full:restore",
        "full:before",
        "full:after",
        "full:tool",
        "full:close",
    ]


@pytest.mark.asyncio
async def test_capability_runtime_preserves_dependency_order_and_closes_once() -> None:
    events: list[str] = []
    dependency = _FullCapability(events, "dependency")
    dependent = _FullCapability(events, "dependent")
    registry = CapabilityRegistry()
    registry.register(_full_spec(dependent, requires=frozenset({"dependency"})))
    registry.register(_full_spec(dependency))
    lifecycle = CapabilityRuntime(registry)

    await lifecycle.before_turn()
    await lifecycle.after_turn()
    await lifecycle.close()
    await lifecycle.close()

    assert events == [
        "dependency:before",
        "dependent:before",
        "dependency:after",
        "dependent:after",
        "dependent:close",
        "dependency:close",
    ]
