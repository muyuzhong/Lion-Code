"""每次 Provider 请求前生成 Agent 状态栏的无状态 Capability。"""

from __future__ import annotations

from ...context.types import ContextView
from ..types import CapabilitySpec


class AgentStateLayer:
    """渲染时间、Context 用量、工具活动和最近失败。"""

    layer_id = "agent-state"

    def render(self, view: ContextView) -> str:
        utilization = view.context_utilization
        lines = [
            f"Time: {view.current_time}",
            (
                "Context: "
                f"{_format_tokens(utilization.used_tokens)} / "
                f"{_format_tokens(utilization.limit_tokens)} tokens "
                f"({utilization.percentage:.1f}%),  "
                f"compaction: {utilization.compaction}"
            ),
            "Activity:",
        ]
        if view.tool_totals:
            lines.extend(
                f"- {trace.name}: {trace.count} calls" for trace in view.tool_totals
            )
            if view.other_tool_calls:
                lines.append(f"- other tools: {view.other_tool_calls} calls")
        else:
            lines.append("- none")
        lines.append("Recent activity:")
        lines.extend(f"- {trace.summary}" for trace in view.recent_tool_calls)
        if not view.recent_tool_calls:
            lines.append("- none")
        lines.append("Repeated activity:")
        lines.extend(
            f"- {trace.summary} ×{trace.count}" for trace in view.repeated_tool_calls
        )
        if not view.repeated_tool_calls:
            lines.append("- none")
        lines.append("Recent failures:")
        lines.extend(f"- {failure}" for failure in view.recent_failures)
        if not view.recent_failures:
            lines.append("- none")
        return "\n".join(lines)


def create_agent_state_capability() -> CapabilitySpec:
    """返回无状态的 Agent 状态栏 ContextLayer。"""
    return CapabilitySpec(
        name="agent-state",
        context_layer=AgentStateLayer(),
    )


def _format_tokens(value: int) -> str:
    if abs(value) < 1_000:
        return str(value)
    formatted = f"{value / 1_000:.1f}".rstrip("0").rstrip(".")
    return f"{formatted}k"
