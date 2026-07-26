"""LionCodingSession 阶段 1 验收测试。

用脚本化 FakeProvider 驱动真实 ``Agent``(Core Runtime 路径),验证:
文本/工具闭环的事件流、AgentEnd→SessionAgentEnd→Settled 次序、
运行中入队(steer)、取消、messages 与 JSONL Session 一致。
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lion_code.agent import Agent
from lion_code.application import (
    AgentSettledEvent,
    LionCodingSession,
    QueueUpdateEvent,
    SessionAgentEndEvent,
)
from lion_code.core import AssistantMessage, TextContent, ToolCall
from lion_code.core.events import (
    AgentEndEvent,
    AgentStartEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
)
from lion_code.core.provider_events import AssistantDoneEvent
from lion_code.session_runtime import SessionRepository
from lion_code.tooling.registry import ToolRegistry
from lion_code.tooling.types import LionTool, ToolCapabilities, ToolResult
from lion_code.ui import set_sink


def _echo_lion_tool(gate: "asyncio.Event | None" = None) -> LionTool:
    """echo 工具;传入 gate 时在放行前挂起,用于制造真实的运行中状态。"""

    async def execute(_ctx, _id, arguments, _on_update):
        if gate is not None:
            await gate.wait()
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


class TestLionCodingSession(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._collected: list[tuple[str, dict]] = []
        self._prev_sink = set_sink(lambda kind, data: self._collected.append((kind, data)))
        self._temp_dir = tempfile.TemporaryDirectory()
        self._session_repository = SessionRepository(Path(self._temp_dir.name))

    def tearDown(self) -> None:
        set_sink(self._prev_sink)
        os.environ.pop("LION_CORE_RUNTIME", None)
        self._temp_dir.cleanup()

    def _make_session(self, events: list, registry: ToolRegistry | None = None):
        from core.fakes import FakeProvider

        fake = FakeProvider(events)
        os.environ["LION_CORE_RUNTIME"] = "1"
        with patch("lion_code.agent.create_provider", return_value=fake):
            agent = Agent(
                api_base="https://example.test/v1",
                api_key="test-key",
                tool_registry=registry or ToolRegistry(),
                custom_system_prompt="test",
                session_repository=self._session_repository,
            )
        agent._mcp_initialized = True
        return LionCodingSession(agent), agent, fake

    # ─── 构造约束 ────────────────────────────────────────────

    async def test_requires_core_runtime(self) -> None:
        os.environ["LION_CORE_RUNTIME"] = "0"
        agent = Agent(
            api_base="https://example.test/v1",
            api_key="test-key",
            custom_system_prompt="test",
        )
        with self.assertRaises(ValueError):
            LionCodingSession(agent)

    # ─── 文本闭环与事件次序 ──────────────────────────────────

    async def test_text_round_trip_event_order(self) -> None:
        session, _agent, fake = self._make_session([_stop_event("你好")])

        events = [event async for event in session.prompt("hi")]

        # 首个事件是 AgentStart;AgentEnd 被包装,原始事件不出现。
        self.assertIsInstance(events[0], AgentStartEvent)
        self.assertFalse(any(isinstance(e, AgentEndEvent) for e in events))
        self.assertIsInstance(events[-2], SessionAgentEndEvent)
        self.assertIsInstance(events[-1], AgentSettledEvent)

        self.assertEqual([m.role for m in session.messages], ["user", "assistant"])
        self.assertEqual(session.messages[-1].text, "你好")
        self.assertFalse(session.is_running)
        self.assertEqual(fake.call_count, 1)

    async def test_tool_loop_round_trip(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        session, _agent, _fake = self._make_session(
            [_tooluse_event(), _stop_event()], registry
        )

        events = [event async for event in session.prompt("hi")]

        self.assertTrue(any(isinstance(e, ToolExecutionStartEvent) for e in events))
        self.assertTrue(any(isinstance(e, ToolExecutionEndEvent) for e in events))
        self.assertEqual(
            [m.role for m in session.messages],
            ["user", "assistant", "toolResult", "assistant"],
        )
        self.assertEqual(session.messages[2].text, "echo:hi")
        self.assertIsInstance(events[-1], AgentSettledEvent)

    # ─── 运行中入队 ──────────────────────────────────────────

    async def test_prompt_while_running_requires_streaming_behavior(self) -> None:
        gate = asyncio.Event()
        registry = ToolRegistry()
        registry.register(_echo_lion_tool(gate))
        session, _agent, _fake = self._make_session(
            [_tooluse_event(), _stop_event()], registry
        )

        raised = False
        async for event in session.prompt("hi"):
            if isinstance(event, ToolExecutionStartEvent) and not raised:
                self.assertTrue(session.is_running)
                nested = session.prompt("mid-run")
                with self.assertRaises(RuntimeError):
                    await nested.__anext__()
                await nested.aclose()
                raised = True
                gate.set()
        self.assertTrue(raised)
        self.assertFalse(session.is_running)

    async def test_steering_queued_while_running(self) -> None:
        gate = asyncio.Event()
        registry = ToolRegistry()
        registry.register(_echo_lion_tool(gate))
        # 第一轮 toolUse 挂起;steer 入队后放行,steered 消息进入下一轮。
        session, _agent, _fake = self._make_session(
            [_tooluse_event(), _stop_event("after-steer")], registry
        )

        queue_events: list[QueueUpdateEvent] = []
        async for event in session.prompt("hi"):
            if isinstance(event, ToolExecutionStartEvent) and not queue_events:
                async for queued in session.prompt(
                    "please also do X", streaming_behavior="steer"
                ):
                    self.assertIsInstance(queued, QueueUpdateEvent)
                    queue_events.append(queued)
                gate.set()

        self.assertEqual(len(queue_events), 1)
        self.assertEqual(queue_events[0].steering, ("please also do X",))
        # steered 消息最终进入 transcript。
        user_texts = [m.text for m in session.messages if m.role == "user"]
        self.assertIn("please also do X", user_texts)
        self.assertEqual(session.queued_steering_messages, ())
        self.assertFalse(session.is_running)

    # ─── 取消 ────────────────────────────────────────────────

    async def test_cancel_mid_run_still_settles(self) -> None:
        gate = asyncio.Event()
        registry = ToolRegistry()
        registry.register(_echo_lion_tool(gate))
        # 只脚本一轮 toolUse:工具挂起时取消,第二次模型调用发 aborted。
        session, _agent, _fake = self._make_session([_tooluse_event()], registry)

        events = []
        async for event in session.prompt("hi"):
            events.append(event)
            if isinstance(event, ToolExecutionStartEvent):
                session.cancel()
                gate.set()

        self.assertIsInstance(events[-1], AgentSettledEvent)
        self.assertIsInstance(events[-2], SessionAgentEndEvent)
        self.assertFalse(session.is_running)
        # 取消后可以继续下一轮(队列/状态未泄漏)。
        self.assertEqual(session.queued_steering_messages, ())

    # ─── Durable Session 一致性 ──────────────────────────────

    async def test_messages_match_jsonl_session(self) -> None:
        registry = ToolRegistry()
        registry.register(_echo_lion_tool())
        session, agent, _fake = self._make_session(
            [_tooluse_event(), _stop_event()], registry
        )

        async for _ in session.prompt("hi"):
            pass
        transcript = session.messages
        await session.aclose()

        state = await self._session_repository.load(agent.session_id)
        self.assertIsNotNone(state)
        self.assertEqual(
            [m.role for m in state.messages], [m.role for m in transcript]
        )
        self.assertEqual(state.messages[-1].text, transcript[-1].text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
