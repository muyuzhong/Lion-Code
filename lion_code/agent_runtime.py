"""LionAgentRuntime：把 Provider、Core Agent 与 ToolRuntime 组装成应用运行时。

组装关系：

- ``get_system`` —— 动态读取 Plan/Skill 之后的系统提示；
- ``get_tools`` —— 每轮读取当前 Registry 激活的工具；
- ``prepare_context`` —— 后续接入 Lion Context Manager；
- ``ToolRuntime`` —— 权限、Hook、新鲜度、持久化、审计等中间件。

Core 在每轮调用模型前会重新执行 ``get_tools``、``get_system`` 与
``prepare_context``，因此本运行时不缓存这些值。权限与结果策略完全由
ToolRuntime 的中间件负责，运行时不再额外注入 ``before_tool_call`` /
``after_tool_call``。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from lion_code.adapters import adapt_active_tools
from lion_code.core import (
    AgentEvent,
    AgentHarness,
    AgentHarnessConfig,
    AgentMessage,
    EventListener,
)
from lion_code.core.loop import BeforeToolCalls, PrepareContext
from lion_code.core.messages import UserMessage
from lion_code.core.provider import ModelProvider
from lion_code.tooling import ToolRuntime


class LionAgentRuntime:
    """组装 Provider + Core Harness + ToolRuntime 的应用运行时。"""

    def __init__(
        self,
        *,
        provider: ModelProvider,
        model: str,
        get_system: Callable[[], str],
        tool_runtime: ToolRuntime,
        prepare_context: PrepareContext | None = None,
        max_turns: int | None = None,
        before_tool_calls: BeforeToolCalls | None = None,
    ) -> None:
        self._provider = provider
        self._tool_runtime = tool_runtime

        self.harness = AgentHarness(
            AgentHarnessConfig(
                provider=provider,
                model=model,
                system=get_system(),
                get_system=get_system,
                tools=[],
                get_tools=lambda: adapt_active_tools(self._tool_runtime),
                prepare_context=prepare_context,
                max_turns=max_turns,
                before_tool_calls=before_tool_calls,
                # 权限和结果策略由 ToolRuntime 中间件负责，不在运行时层注入。
                before_tool_call=None,
                after_tool_call=None,
            )
        )

    def subscribe(self, listener: EventListener) -> Callable[[], None]:
        """注册一个同步或异步的 Agent 事件监听器，返回取消订阅回调。"""
        return self.harness.subscribe(listener)

    async def prompt(self, content: str) -> None:
        """驱动一次完整对话：消费完 harness 产生的全部事件。"""
        async for _ in self.harness.prompt(content):
            pass

    async def continue_(self) -> None:
        """使用当前 Harness 上下文继续运行，不追加新的用户消息。"""
        async for _ in self.harness.continue_():
            pass

    def set_model(self, model: str) -> None:
        """更新后续 Provider 请求使用的模型。"""
        self.harness.config.model = model

    @property
    def provider(self) -> ModelProvider:
        """返回摘要与模型限制发现所复用的 Provider。"""

        return self._provider

    async def replace_active_context(self, messages: Sequence[AgentMessage]) -> None:
        """替换模型活跃上下文；durable history 仍由 SessionRecorder 保留。"""

        self.harness.clear_queues()
        self.harness.replace_messages(messages)

    async def reset_active_context(self, content: str) -> None:
        """只替换模型活跃上下文；durable history 由 SessionRecorder 保留。"""

        await self.replace_active_context([UserMessage(content=content)])

    def cancel(self) -> None:
        """请求取消当前正在进行的模型流。"""
        self.harness.cancel()

    @property
    def messages(self) -> tuple[AgentMessage, ...]:
        """返回当前对话的消息快照。"""
        return self.harness.messages
