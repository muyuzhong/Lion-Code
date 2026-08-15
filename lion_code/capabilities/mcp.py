"""MCP Capability: lazy tool discovery and registration as a TurnParticipant.

The MCP capability owns the *discovery and registration* of MCP tools at
the start of the first turn.  It does **not** own the MCP process lifecycle
(``disconnect_all`` remains owned by ``ToolEnvironment``).

The capability receives narrow dependencies (manager, registry, notice
emitter, init-flag accessors) rather than a reference to ``Agent``.
"""

from __future__ import annotations

from collections.abc import Callable

from ..mcp_client import McpManager
from ..tooling.mcp import create_mcp_tool
from ..tooling.registry import ToolRegistry
from .types import CapabilitySpec, TurnParticipant


class McpCapability(TurnParticipant):
    """Discovers and registers MCP tools on the first ``before_turn``.

    The capability is registered only for root agents that own the MCP
    manager.  Discovery failures are emitted as notices (fail-soft),
    matching the existing behavior.

    The init flag is shared with the Agent composition root via callables
    so that tests and lifecycle code that check ``agent._mcp_initialized``
    continue to work.
    """

    def __init__(
        self,
        *,
        mcp_manager: McpManager | None,
        tool_registry: ToolRegistry,
        emit_notice: Callable[[str], None],
        is_already_initialized: Callable[[], bool],
        mark_initialized: Callable[[], None],
        is_root: bool,
    ) -> None:
        self._mcp_manager = mcp_manager
        self._tool_registry = tool_registry
        self._emit_notice = emit_notice
        self._is_already_initialized = is_already_initialized
        self._mark_initialized = mark_initialized
        self._is_root = is_root

    async def before_turn(self) -> None:
        """Discover and register MCP tools once; fail-soft on error."""
        if not self._is_root or self._is_already_initialized():
            return
        if self._mcp_manager is None:
            return
        self._mark_initialized()
        try:
            definitions = await self._mcp_manager.discover_tools()
            for definition in definitions:
                self._tool_registry.register(
                    create_mcp_tool(self._mcp_manager, definition)
                )
        except Exception as error:  # noqa: BLE001
            self._emit_notice(f"[mcp] Init failed: {error}")

    async def after_turn(self) -> None:
        """No post-turn action needed for MCP."""

    @property
    def spec(self) -> CapabilitySpec:
        return CapabilitySpec(
            name="mcp",
            turn_participants=(self,),
        )
