"""Agent 入口灰度切换集成测试：证明真实 ``Agent.chat`` 已切到新 Core Runtime。

通过 patch ``lion_code.agent.create_provider`` 注入脚本化 ``FakeProvider``，
验证 ``LION_CORE_RUNTIME=1`` 时 ``chat`` 走 LionAgentRuntime 而非旧
``_chat_openai``，并覆盖工具闭环、动态 system、动态工具、取消后继续会话。
``LION_CORE_RUNTIME=0`` 时仍走旧路径。
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from lion_code.agent import Agent
from lion_code.core import AssistantMessage, TextContent, ToolCall, TurnEndEvent
from lion_code.core.provider_events import AssistantDoneEvent
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.types import LionTool, ToolCapabilities, ToolResult
from lion_code.ui import set_sink

from core.fakes import FakeProvider


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


def _stop_event(text: str = "done") -> AssistantDoneEvent:
    return AssistantDoneEvent(
        reason="stop",
        message=AssistantMessage(
            model="fake",
            content=[TextContent(text=text)],
            stop_reason="stop",
        ),
    )


class TestAgentCoreRuntime(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # 捕获所有 ui 输出，避免测试污染 stdout。
        self._collected: list[tuple[str, dict]] = []
        self._prev_sink = set_sink(lambda kind, data: self._collected.append((kind, data)))

    def tearDown(self) -> None:
        set_sink(self._prev_sink)
        os.environ.pop("LION_CORE_RUNTIME", None)

    def _make_agent(self, events: list, registry: ToolRegistry) -> tuple[Agent, FakeProvider]:
        fake = FakeProvider(events)
        os.environ["LION_CORE_RUNTIME"] = "1"
        with patch("lion_code.agent.create_provider", return_value=fake):
            agent = Agent(
                api_base="https://example.test/v1",
                api_key="test-key",
                tool_registry=registry,
                custom_system_prompt="test",
            )
        # 跳过 MCP 发现，避免测试环境副作用。
        agent._mcp_initialized = True
        return agent, fake

    async def test_grayscale_off_uses_old_path(self) -> None:
        os.environ["LION_CORE_RUNTIME"] = "0"
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        agent = Agent(
            api_base="https://example.test/v1",
            api_key="test-key",
            tool_registry=registry,
            custom_system_prompt="test",
        )
        agent._mcp_initialized = True

        self.assertIsNone(agent._core_runtime)
        self.assertFalse(agent._use_core_runtime)

        with (
            patch.object(Agent, "_chat_openai", new_callable=AsyncMock) as mock_chat,
            patch.object(Agent, "_auto_save", lambda self: None),
        ):
            await agent.chat("hello")

        mock_chat.assert_called_once_with("hello")

    async def test_grayscale_on_routes_to_core_runtime(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        agent, fake = self._make_agent([_stop_event("done")], registry)

        self.assertIsNotNone(agent._core_runtime)

        with patch.object(Agent, "_chat_openai", new_callable=AsyncMock) as mock_chat:
            await agent.chat("hello")

        # 不再调用旧路径。
        mock_chat.assert_not_called()
        self.assertEqual(agent._core_runtime.messages[-1].text, "done")
        self.assertEqual(fake.call_count, 1)

    async def test_tool_loop_through_runtime(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        agent, fake = self._make_agent([_tooluse_event(), _stop_event("done")], registry)

        await agent.chat("hello")

        messages = agent._core_runtime.messages
        self.assertEqual(
            [m.role for m in messages],
            ["user", "assistant", "toolResult", "assistant"],
        )
        self.assertEqual(messages[2].text, "echo:hi")
        self.assertFalse(messages[2].is_error)
        self.assertEqual(messages[-1].text, "done")
        self.assertEqual(fake.call_count, 2)

    async def test_dynamic_system_prompt_refetched_per_turn(self) -> None:
        # 模拟 Plan 模式切换：运行中改 _system_prompt，下一轮请求必须看到新值。
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        agent, fake = self._make_agent([_tooluse_event(), _stop_event("done")], registry)
        agent._system_prompt = "initial"

        mutated = {"done": False}

        async def mutate_after_first_turn(event) -> None:
            if not mutated["done"] and isinstance(event, TurnEndEvent):
                agent._system_prompt = "plan-prompt"
                mutated["done"] = True

        agent._core_runtime.subscribe(mutate_after_first_turn)
        await agent.chat("hello")

        self.assertEqual(fake.received_systems, ["initial", "plan-prompt"])

    async def test_dynamic_tools_refetched_per_turn(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        agent, fake = self._make_agent([_tooluse_event(), _stop_event("done")], registry)

        added = {"done": False}

        async def activate_after_first_turn(event) -> None:
            if not added["done"] and isinstance(event, TurnEndEvent):
                registry.register(_named_lion_tool("late"))
                added["done"] = True

        agent._core_runtime.subscribe(activate_after_first_turn)
        await agent.chat("hello")

        self.assertNotIn("late", fake.received_tools[0])
        self.assertIn("late", fake.received_tools[1])

    async def test_cancel_then_continue_without_incomplete_tool_call(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        agent, fake = self._make_agent([_tooluse_event(), _stop_event("done")], registry)

        cancelled = {"done": False}

        async def cancel_after_first_turn(event) -> None:
            if not cancelled["done"] and isinstance(event, TurnEndEvent):
                agent._core_runtime.cancel()
                cancelled["done"] = True

        agent._core_runtime.subscribe(cancel_after_first_turn)
        await agent.chat("hello")

        # 第一轮工具已执行，第二轮被取消，最终消息为 aborted。
        self.assertEqual(agent._core_runtime.messages[-1].stop_reason, "aborted")

        # 再次 chat：不遗留不完整工具调用，能正常收敛到最终文本。
        await agent.chat("again")
        self.assertEqual(agent._core_runtime.messages[-1].text, "done")
        # 第一轮 + 被取消的第二轮 + 续聊一轮，共 3 次 provider 调用。
        self.assertEqual(fake.call_count, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
