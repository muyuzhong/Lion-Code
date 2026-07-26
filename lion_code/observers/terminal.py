"""终端渲染观察器：把 Agent 事件流渲染为终端输出。

仅消费 Core 的 Agent 事件并委托给 :mod:`lion_code.ui` 的现有 ``print_*`` 与
spinner 函数，不引入新的输出通道。权限拒绝等结构化错误已经以
``ToolExecutionEndEvent(is_error=True)`` 传播，本观察器只负责呈现，不再
执行任何权限或重试逻辑。
"""

from __future__ import annotations

from lion_code.core.events import (
    AgentEndEvent,
    AgentEvent,
    AgentStartEvent,
    MessageEndEvent,
    MessageUpdateEvent,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
)
from lion_code.core.messages import AssistantMessage
from lion_code.core.provider_events import (
    AssistantErrorEvent,
    TextDeltaEvent,
)
from lion_code.ui import (
    print_assistant_text,
    print_divider,
    print_error,
    print_tool_call,
    print_tool_result,
    start_spinner,
    stop_spinner,
)


class TerminalRenderer:
    """把 Agent 事件流渲染到终端的异步观察器。"""

    def __init__(self) -> None:
        self._streaming_text = False

    async def handle(self, event: AgentEvent) -> None:
        if isinstance(event, AgentStartEvent):
            self._streaming_text = False
            start_spinner("Thinking")
            return

        if isinstance(event, MessageUpdateEvent):
            provider_event = event.assistant_message_event

            if isinstance(provider_event, TextDeltaEvent):
                if not self._streaming_text:
                    stop_spinner()
                    self._streaming_text = True
                print_assistant_text(provider_event.delta)
                return

            if isinstance(provider_event, AssistantErrorEvent):
                stop_spinner()
                print_error(provider_event.error.error_message or "Model request failed")
                return
            return

        if isinstance(event, ToolExecutionStartEvent):
            stop_spinner()
            self._streaming_text = False
            print_tool_call(event.tool_name, event.args)
            start_spinner("Running tool")
            return

        if isinstance(event, ToolExecutionEndEvent):
            stop_spinner()
            print_tool_result(event.tool_name, event.result.text)
            if event.is_error:
                print_error(event.result.text)
            start_spinner("Thinking")
            return

        if isinstance(event, MessageEndEvent):
            if (
                isinstance(event.message, AssistantMessage)
                and event.message.stop_reason == "error"
            ):
                stop_spinner()
                print_error(event.message.error_message or "Model request failed")
            return

        if isinstance(event, AgentEndEvent):
            stop_spinner()
            print_divider()
