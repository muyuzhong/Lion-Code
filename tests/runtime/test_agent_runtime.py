"""``LionAgentRuntime`` 组装闭环测试。

用脚本化、信号感知的 ``FakeProvider``（记录每轮收到的 system/tools）
驱动 LionAgentRuntime -> AgentHarness -> ToolRuntime -> LionTool 的完整
闭环，覆盖：基础闭环、每轮重新读取 system、每轮重新读取工具、取消传播。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from lion_code.agent_runtime import LionAgentRuntime
from lion_code.core import AssistantMessage, TextContent, ToolCall, TurnEndEvent, Usage
from lion_code.core.provider_events import AssistantDoneEvent
from lion_code.observers import TerminalRenderer, UsageObserver
from lion_code.tooling.context import ToolContext
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.runtime import ToolRuntime
from lion_code.tooling.types import LionTool, ToolCapabilities, ToolResult
from lion_code.ui import set_sink

from core.fakes import FakeProvider


class _Controller:
    pass


def _context(registry: ToolRegistry) -> ToolContext:
    return ToolContext(
        session_id="session",
        cwd=Path.cwd(),
        controller=_Controller(),
        registry=registry,
        permission_mode="default",
        plan_file_path=None,
        read_file_state={},
    )


def _echo_lion_tool() -> LionTool:
    async def execute(_ctx, _id, arguments, _on_update):
        return ToolResult(content=f"echo:{arguments.get('msg', '')}")

    return LionTool(
        name="echo",
        label="Echo",
        description="echo the msg argument",
        parameters={
            "type": "object",
            "properties": {"msg": {"type": "string"}},
            "required": ["msg"],
        },
        execute_fn=execute,
        capabilities=ToolCapabilities(read_only=True, concurrency_safe=True),
        execution_mode="parallel",
    )


def _named_lion_tool(name: str) -> LionTool:
    async def execute(_ctx, _id, _args, _on_update):
        return ToolResult(content=f"{name}-result")

    return LionTool(
        name=name,
        label=name,
        description=name,
        parameters={"type": "object"},
        execute_fn=execute,
        capabilities=ToolCapabilities(read_only=True, concurrency_safe=True),
        execution_mode="parallel",
    )


def _tooluse_event() -> AssistantDoneEvent:
    return AssistantDoneEvent(
        reason="toolUse",
        message=AssistantMessage(
            model="fake",
            content=[ToolCall(id="c1", name="echo", arguments={"msg": "hi"})],
            stop_reason="toolUse",
        ),
    )


def _stop_event(text: str = "done", usage: Usage | None = None) -> AssistantDoneEvent:
    return AssistantDoneEvent(
        reason="stop",
        message=AssistantMessage(
            model="fake",
            content=[TextContent(text=text)],
            stop_reason="stop",
            usage=usage or Usage(),
        ),
    )


def _runtime_with_echo() -> tuple[ToolRegistry, ToolRuntime]:
    registry = ToolRegistry()
    registry.register(_echo_lion_tool())
    return registry, ToolRuntime(registry, _context(registry))


class TestLionAgentRuntimeLoop(unittest.IsolatedAsyncioTestCase):
    async def test_closed_loop_through_tool_runtime(self) -> None:
        provider = FakeProvider([_tooluse_event(), _stop_event()])
        _registry, tool_runtime = _runtime_with_echo()
        runtime = LionAgentRuntime(
            provider=provider,
            model="fake",
            get_system=lambda: "s",
            tool_runtime=tool_runtime,
        )

        await runtime.prompt("hello")

        messages = runtime.messages
        self.assertEqual(
            [m.role for m in messages],
            ["user", "assistant", "toolResult", "assistant"],
        )
        self.assertEqual(messages[2].text, "echo:hi")
        self.assertFalse(messages[2].is_error)
        self.assertEqual(messages[-1].text, "done")
        self.assertEqual(provider.call_count, 2)

    async def test_system_prompt_is_refetched_per_turn(self) -> None:
        # 工具执行后修改 system，第二次 provider 请求必须看到新值。
        holder = {"s": "initial"}
        provider = FakeProvider([_tooluse_event(), _stop_event()])
        _registry, tool_runtime = _runtime_with_echo()
        runtime = LionAgentRuntime(
            provider=provider,
            model="fake",
            get_system=lambda: holder["s"],
            tool_runtime=tool_runtime,
        )

        mutated = {"done": False}

        async def mutate_after_first_turn(event) -> None:
            if not mutated["done"] and isinstance(event, TurnEndEvent):
                holder["s"] = "updated"
                mutated["done"] = True

        runtime.subscribe(mutate_after_first_turn)
        await runtime.prompt("hello")

        self.assertEqual(provider.received_systems, ["initial", "updated"])

    async def test_tools_are_refetched_per_turn(self) -> None:
        # 工具激活后，第二次 provider 请求必须看到新工具。
        provider = FakeProvider([_tooluse_event(), _stop_event()])
        registry, tool_runtime = _runtime_with_echo()
        runtime = LionAgentRuntime(
            provider=provider,
            model="fake",
            get_system=lambda: "s",
            tool_runtime=tool_runtime,
        )

        added = {"done": False}

        async def activate_after_first_turn(event) -> None:
            if not added["done"] and isinstance(event, TurnEndEvent):
                registry.register(_named_lion_tool("late"))
                added["done"] = True

        runtime.subscribe(activate_after_first_turn)
        await runtime.prompt("hello")

        self.assertNotIn("late", provider.received_tools[0])
        self.assertIn("late", provider.received_tools[1])

    async def test_cancel_aborts_run(self) -> None:
        # runtime.cancel() 经 harness 信号传播到 provider，最终产生 aborted 消息。
        provider = FakeProvider([_tooluse_event(), _stop_event()])
        _registry, tool_runtime = _runtime_with_echo()
        runtime = LionAgentRuntime(
            provider=provider,
            model="fake",
            get_system=lambda: "s",
            tool_runtime=tool_runtime,
        )

        cancelled = {"done": False}

        async def cancel_after_first_turn(event) -> None:
            if not cancelled["done"] and isinstance(event, TurnEndEvent):
                runtime.cancel()
                cancelled["done"] = True

        runtime.subscribe(cancel_after_first_turn)
        await runtime.prompt("hello")

        self.assertEqual(runtime.messages[-1].stop_reason, "aborted")
        # 第一轮 + 被取消的第二轮，provider 被调用两次。
        self.assertEqual(provider.call_count, 2)

    async def test_observers_wired_to_runtime(self) -> None:
        # 真正组装：LionAgentRuntime + TerminalRenderer + UsageObserver 同时工作。
        provider = FakeProvider(
            [_tooluse_event(), _stop_event(usage=Usage(input=10, output=5, total_tokens=15))]
        )
        _registry, tool_runtime = _runtime_with_echo()
        runtime = LionAgentRuntime(
            provider=provider,
            model="fake",
            get_system=lambda: "s",
            tool_runtime=tool_runtime,
        )

        renderer = TerminalRenderer()
        usage = UsageObserver()
        collected: list[tuple[str, dict]] = []
        prev_sink = set_sink(lambda kind, data: collected.append((kind, data)))
        try:
            runtime.subscribe(renderer.handle)
            runtime.subscribe(usage.handle)
            await runtime.prompt("hello")
        finally:
            set_sink(prev_sink)

        # UsageObserver 累计了最终助手消息的用量。
        self.assertEqual(usage.totals.input_tokens, 10)
        self.assertEqual(usage.totals.output_tokens, 5)
        # TerminalRenderer 渲染了工具调用、结果与结束分隔线。
        kinds = [kind for kind, _ in collected]
        self.assertIn("tool_call", kinds)
        self.assertIn("tool_result", kinds)
        self.assertIn("divider", kinds)


if __name__ == "__main__":
    unittest.main(verbosity=2)
