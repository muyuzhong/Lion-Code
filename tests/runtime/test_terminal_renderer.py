"""``TerminalRenderer`` 事件->终端输出映射测试。

直接替换 Renderer 导入的 print_* / spinner 函数，验证各 Agent 事件被正确
映射，且不实际写 stdout。
"""

from __future__ import annotations

import unittest
from contextlib import ExitStack
from unittest.mock import patch

from lion_code.core import (
    AgentEndEvent,
    AgentStartEvent,
    AgentToolResult,
    AssistantMessage,
    MessageEndEvent,
    MessageUpdateEvent,
    TextContent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
)
from lion_code.core.provider_events import AssistantErrorEvent, TextDeltaEvent
from lion_code.observers import TerminalRenderer


class TestTerminalRenderer(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._collected: list[tuple[str, dict]] = []
        self._patches = ExitStack()
        self._patches.enter_context(
            patch(
                "lion_code.observers.terminal.start_spinner",
                side_effect=lambda label="Thinking": self._collected.append(
                    ("spinner", {"on": True, "label": label})
                ),
            )
        )
        self._patches.enter_context(
            patch(
                "lion_code.observers.terminal.stop_spinner",
                side_effect=lambda: self._collected.append(("spinner", {"on": False})),
            )
        )
        self._patches.enter_context(
            patch(
                "lion_code.observers.terminal.print_assistant_text",
                side_effect=lambda text: self._collected.append(("text", {"text": text})),
            )
        )
        self._patches.enter_context(
            patch(
                "lion_code.observers.terminal.print_tool_call",
                side_effect=lambda name, inp: self._collected.append(
                    ("tool_call", {"name": name, "input": inp})
                ),
            )
        )
        self._patches.enter_context(
            patch(
                "lion_code.observers.terminal.print_tool_result",
                side_effect=lambda name, text: self._collected.append(
                    ("tool_result", {"name": name, "text": text})
                ),
            )
        )
        self._patches.enter_context(
            patch(
                "lion_code.observers.terminal.print_error",
                side_effect=lambda message: self._collected.append(
                    ("error", {"message": message})
                ),
            )
        )
        self._patches.enter_context(
            patch(
                "lion_code.observers.terminal.print_divider",
                side_effect=lambda: self._collected.append(("divider", {})),
            )
        )
        self._renderer = TerminalRenderer()

    def tearDown(self) -> None:
        self._patches.close()

    def _events_of(self, kind: str) -> list[dict]:
        return [data for k, data in self._collected if k == kind]

    async def test_agent_start_starts_thinking_spinner(self) -> None:
        await self._renderer.handle(AgentStartEvent())
        self.assertIn(("spinner", {"on": True, "label": "Thinking"}), self._collected)

    async def test_text_delta_stops_spinner_then_prints_text(self) -> None:
        await self._renderer.handle(AgentStartEvent())
        await self._renderer.handle(
            MessageUpdateEvent(
                message=AssistantMessage(content="hi"),
                assistant_message_event=TextDeltaEvent(
                    content_index=0, delta="hi", partial=AssistantMessage()
                ),
            )
        )

        self.assertIn(("text", {"text": "hi"}), self._collected)
        spinner_off_idx = self._collected.index(("spinner", {"on": False}))
        text_idx = self._collected.index(("text", {"text": "hi"}))
        self.assertLess(spinner_off_idx, text_idx)

    async def test_tool_start_prints_tool_call(self) -> None:
        await self._renderer.handle(
            ToolExecutionStartEvent(tool_call_id="c1", tool_name="echo", args={"msg": "hi"})
        )
        tool_calls = self._events_of("tool_call")
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0]["name"], "echo")

    async def test_tool_end_prints_tool_result(self) -> None:
        await self._renderer.handle(
            ToolExecutionEndEvent(
                tool_call_id="c1",
                tool_name="echo",
                result=AgentToolResult(content=[TextContent(text="echo:hi")]),
                is_error=False,
            )
        )
        results = self._events_of("tool_result")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["text"], "echo:hi")

    async def test_tool_end_error_also_prints_error(self) -> None:
        await self._renderer.handle(
            ToolExecutionEndEvent(
                tool_call_id="c1",
                tool_name="echo",
                result=AgentToolResult(content=[TextContent(text="denied")]),
                is_error=True,
            )
        )
        errors = self._events_of("error")
        self.assertEqual(len(errors), 1)
        self.assertIn("denied", errors[0]["message"])

    async def test_assistant_error_event_prints_error(self) -> None:
        await self._renderer.handle(
            MessageUpdateEvent(
                message=AssistantMessage(stop_reason="error", error_message="boom"),
                assistant_message_event=AssistantErrorEvent(
                    reason="error",
                    error=AssistantMessage(stop_reason="error", error_message="boom"),
                ),
            )
        )
        errors = self._events_of("error")
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["message"], "boom")

    async def test_message_end_error_prints_error(self) -> None:
        await self._renderer.handle(
            MessageEndEvent(
                message=AssistantMessage(stop_reason="error", error_message="msg failed")
            )
        )
        errors = self._events_of("error")
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["message"], "msg failed")

    async def test_agent_end_stops_spinner_and_prints_divider(self) -> None:
        await self._renderer.handle(AgentEndEvent())
        self.assertIn(("divider", {}), self._collected)
        self.assertIn(("spinner", {"on": False}), self._collected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
