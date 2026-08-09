"""取消契约：运行中的任务经由 Provider 流中止。"""

from __future__ import annotations

import unittest

from lion_code.core import (
    AgentEndEvent,
    AgentHarness,
    AgentHarnessConfig,
    AgentTool,
    AgentToolResult,
    AssistantMessage,
    CancellationToken,
    TextContent,
    ToolCall,
    TurnEndEvent,
)
from lion_code.core.provider_events import AssistantDoneEvent, AssistantErrorEvent
from lion_code.execution_control import ExecutionControl

from .fakes import FakeProvider


def _noop_tool() -> AgentTool:
    async def execute(tool_call_id, arguments, signal, on_update):
        return AgentToolResult(content=[TextContent(text="ok")], details={})

    return AgentTool(
        name="noop",
        label="Noop",
        description="no-op tool",
        parameters={},
        execute_fn=execute,
    )


class TestHarnessCancel(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_after_start_before_iteration_is_not_reset(self) -> None:
        provider = FakeProvider(
            [
                AssistantDoneEvent(
                    reason="stop",
                    message=AssistantMessage(model="fake", content="unreachable"),
                )
            ]
        )
        harness = AgentHarness(
            AgentHarnessConfig(provider=provider, model="fake", system="test")
        )

        events = harness.prompt("hello")
        harness.cancel()
        async for _ in events:
            pass

        self.assertEqual(provider.call_count, 1)
        self.assertEqual(harness.messages[-1].stop_reason, "aborted")
        self.assertNotIn("unreachable", [message.text for message in harness.messages])

    async def test_cancel_aborts_run_after_turn(self) -> None:
        # 第一轮请求工具调用；在两轮之间取消，使下一次 Provider 流直接中止。
        provider = FakeProvider(
            [
                AssistantDoneEvent(
                    reason="toolUse",
                    message=AssistantMessage(
                        model="fake",
                        content=[ToolCall(id="c1", name="noop", arguments={})],
                        stop_reason="toolUse",
                    ),
                ),
                AssistantDoneEvent(
                    reason="stop",
                    message=AssistantMessage(
                        model="fake",
                        content=[TextContent(text="final")],
                        stop_reason="stop",
                    ),
                ),
            ]
        )

        harness = AgentHarness(
            AgentHarnessConfig(
                provider=provider,
                model="fake",
                system="test",
                tools=[_noop_tool()],
            )
        )

        events = []
        cancelled = False
        async for event in harness.prompt("hello"):
            events.append(event)
            if not cancelled and isinstance(event, TurnEndEvent):
                harness.cancel()
                cancelled = True

        # 中止流返回后，本次运行正常结束并发出 AgentEnd。
        self.assertTrue(any(isinstance(e, AgentEndEvent) for e in events))
        # Provider 收到两次调用：第一轮和被中止的第二轮。
        self.assertEqual(provider.call_count, 2)
        # 被取消的流生成 aborted Assistant，作为最终消息。
        self.assertEqual(harness.messages[-1].stop_reason, "aborted")
        # 未实际到达的 final 文本不能进入历史。
        self.assertNotIn("final", [getattr(m, "text", "") for m in harness.messages])

        async for _ in harness.prompt("again"):
            pass

        self.assertEqual(harness.messages[-1].text, "final")

    async def test_shared_token_reaches_provider_and_tool(self) -> None:
        provider = FakeProvider(
            [
                AssistantDoneEvent(
                    reason="toolUse",
                    message=AssistantMessage(
                        model="fake",
                        content=[ToolCall(id="c1", name="capture", arguments={})],
                        stop_reason="toolUse",
                    ),
                ),
                AssistantDoneEvent(
                    reason="stop",
                    message=AssistantMessage(model="fake", content="done"),
                ),
            ]
        )
        received_signals = []

        async def execute(tool_call_id, arguments, signal, on_update):
            received_signals.append(signal)
            return AgentToolResult(content="ok")

        token = CancellationToken()
        harness = AgentHarness(
            AgentHarnessConfig(
                provider=provider,
                model="fake",
                system="test",
                tools=[
                    AgentTool(
                        name="capture",
                        label="Capture",
                        description="capture cancellation signal",
                        parameters={},
                        execute_fn=execute,
                    )
                ],
            ),
            cancellation=token,
        )

        async for _ in harness.prompt("hello"):
            pass

        self.assertTrue(all(signal is token for signal in provider.received_signals))
        self.assertEqual(received_signals, [token])

    async def test_error_event_reason_overrides_message_stop_reason(self) -> None:
        provider = FakeProvider(
            [
                AssistantErrorEvent(
                    reason="aborted",
                    error=AssistantMessage(model="fake"),
                )
            ]
        )
        harness = AgentHarness(
            AgentHarnessConfig(
                provider=provider,
                model="fake",
                system="test",
            )
        )

        async for _ in harness.prompt("hello"):
            pass

        self.assertEqual(harness.messages[-1].stop_reason, "aborted")


class TestCancellationToken(unittest.TestCase):
    def test_cancel_and_reset_share_one_state(self) -> None:
        token = CancellationToken()

        self.assertFalse(token.cancelled)
        self.assertFalse(token.is_cancelled())
        token.cancel()
        self.assertTrue(token.cancelled)
        self.assertTrue(token.is_cancelled())
        token.reset()
        self.assertFalse(token.cancelled)

    def test_execution_begin_resets_previous_cancellation(self) -> None:
        execution = ExecutionControl()

        execution.cancel()
        self.assertTrue(execution.cancelled)
        execution.begin()
        self.assertFalse(execution.cancelled)


if __name__ == "__main__":
    unittest.main(verbosity=2)
