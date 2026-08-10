"""Adapt Lion's policy-aware tool runtime to the portable agent core."""

from __future__ import annotations

from collections.abc import Mapping

from lion_code.core.cancellation import CancellationView
from lion_code.core.messages import ImageContent, TextContent
from lion_code.core.tools import (
    AgentTool,
    AgentToolResult,
    ToolExecutionMode,
)
from lion_code.core.tools import (
    ToolUpdateCallback as CoreToolUpdateCallback,
)
from lion_code.core.types import JSONValue as CoreJSONValue
from lion_code.tooling import LionTool, ToolRuntime
from lion_code.tooling.types import (
    ToolResult as LionToolResult,
)


def to_core_result(result: LionToolResult) -> AgentToolResult:
    """Convert a Lion ``ToolResult`` without losing policy/runtime metadata."""

    content: list[TextContent | ImageContent] = (
        [TextContent(text=result.content)] if result.content else []
    )
    return AgentToolResult(
        content=content,
        details=result.details,
        added_tool_names=result.activated_tools or None,
        terminate=result.terminate or None,
        is_error=result.is_error,
    )


def adapt_lion_tool(tool: LionTool, runtime: ToolRuntime) -> AgentTool:
    """Expose one LionTool through the provider-neutral Core contract.

    Execution is delegated to ``ToolRuntime.execute`` so Lion's middleware chain
    (cancellation, pre-tool hooks, permission, read-before-write freshness, result
    persistence, audit) runs exactly once per call. The host must not install a
    parallel ``before_tool_call``/``after_tool_call`` policy on the harness, or
    permission and result policy would execute twice.
    """

    async def execute(
        tool_call_id: str,
        arguments: Mapping[str, CoreJSONValue],
        signal: CancellationView | None = None,
        on_update: CoreToolUpdateCallback | None = None,
    ) -> AgentToolResult:
        # Check Core cancellation before entering Lion's middleware chain. The
        # loop also checks before calling the tool; this guards the narrow race
        # where the signal is set between that check and runtime entry.
        if signal is not None and signal.is_cancelled():
            return AgentToolResult(
                content=[TextContent(text="Tool call cancelled.")],
                is_error=True,
            )

        def forward_update(update: LionToolResult) -> None:
            if on_update is not None:
                on_update(to_core_result(update))

        result = await runtime.execute(
            tool_call_id=tool_call_id,
            name=tool.name,
            arguments=arguments,
            on_update=forward_update,
            cancellation=signal,
        )

        return to_core_result(result)

    # Do not trust ``tool.execution_mode`` alone. A tool may declare ``parallel``
    # but still be ineligible unless it is also read-only and concurrency-safe.
    # Lion encodes that rule in ``ToolRuntime.can_run_parallel``.
    execution_mode: ToolExecutionMode = (
        "parallel" if runtime.can_run_parallel(tool.name) else "sequential"
    )

    return AgentTool(
        name=tool.name,
        label=tool.label,
        description=tool.description,
        parameters=tool.parameters,
        execute_fn=execute,
        prompt_snippet=tool.prompt_snippet,
        prompt_guidelines=tool.prompt_guidelines,
        execution_mode=execution_mode,
    )


def adapt_active_tools(runtime: ToolRuntime) -> list[AgentTool]:
    """Return the current Agent instance's active Core tool view.

    Lion's registry tracks per-instance activation state, so deferred tools
    activated by ``tool_search`` (or any other tool) appear here on the next
    model request without the adapter caching a tool list.
    """

    return [
        adapt_lion_tool(tool, runtime)
        for tool in runtime.registry.active_tools()
    ]
