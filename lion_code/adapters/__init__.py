"""Adapt Lion's policy-aware tool runtime to the portable agent core.

The portable core (``lion_code.core``) must not depend on Lion's tooling layer.
This package is the one place that depends on both: it translates Lion tools and
their structured results into the provider-neutral ``AgentTool`` / ``AgentToolResult``
contract so the core loop can drive Lion's real ``ToolRuntime`` (middleware,
permission, hooks, freshness, result persistence) without a second policy stack.
"""

from .tool_adapter import adapt_active_tools, adapt_lion_tool, to_core_result

__all__ = [
    "adapt_active_tools",
    "adapt_lion_tool",
    "to_core_result",
]
