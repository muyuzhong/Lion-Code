"""LionCodingSession:面向前端的应用会话门面(阶段 1 最小面)。

职责与边界:

- 对外提供 ``prompt``/``continue_``/``cancel``/``is_running``/``messages``/
  队列快照/``aclose``,事件以 ``AsyncIterator[LionSessionEvent]`` 流出;
- 内部组合现有 ``Agent``(Core Runtime 路径)作为实现细节:Agent 已经
  完成 Provider/ToolRuntime/SessionRecorder/ContextManager/MemoryCoordinator
  的组装与每轮编排,本层不重复实现任何 Loop;
- 底层 ``AgentEvent`` 原样透传,唯 ``AgentEndEvent`` 包装为
  ``SessionAgentEndEvent``;一次调用彻底结束后追加 ``AgentSettledEvent``;
- 运行中再次 ``prompt`` 必须显式指定 ``streaming_behavior``,消息进入
  Harness 的 steering / follow-up 队列并发出 ``QueueUpdateEvent``。

仅支持启用 Core Runtime 的 Agent:旧 SDK 路径没有结构化事件流,
无法支撑本层契约。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from lion_code.core.events import AgentEndEvent, AgentEvent
from lion_code.core.messages import AgentMessage

from .commands import CommandRegistry, CommandResult, create_default_command_registry
from .prompt_templates import PromptTemplate
from .skills import Skill
from .events import (
    AgentSettledEvent,
    LionSessionEvent,
    QueueUpdateEvent,
    SessionAgentEndEvent,
)

if TYPE_CHECKING:
    from lion_code.agent import Agent

type StreamingBehavior = Literal["steer", "follow_up"]




class LionCodingSession:
    """把 ``Agent``(Core Runtime 路径)包装为前端可消费的会话门面。"""

    def __init__(self, agent: Agent) -> None:
        runtime = agent.core_runtime
        if runtime is None:
            raise ValueError(
                "LionCodingSession 需要启用 Core Runtime"
                "(LION_CORE_RUNTIME=1 且 OpenAI-compatible 后端)"
            )
        self._agent = agent
        self._runtime = runtime
        self._running = False
        self._command_registry = create_default_command_registry()
        self._skills_cache: tuple[Skill, ...] | None = None

    # ─── 环境 / 身份 ─────────────────────────────────────────

    @property
    def cwd(self) -> Path:
        return Path(self._agent.tool_context.cwd)

    @property
    def model(self) -> str:
        return self._agent.model

    @property
    def provider_name(self) -> str:
        return "openai-compatible" if self._agent.use_openai else "anthropic"

    @property
    def permission_mode(self) -> str:
        return self._agent.permission_mode

    @property
    def session_id(self) -> str:
        return self._agent.session_id

    @property
    def api_configured(self) -> bool:
        return self._agent.api_configured

    # ─── 状态 ────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        """本会话是否有未归位的一轮。

        从事件流开始消费到 Settled 之间恒为 True——即使底层协程已经
        结束、事件仍在排空,也算未归位;前端以 Settled 为空闲信号。
        """
        return self._running

    @property
    def messages(self) -> tuple[AgentMessage, ...]:
        """Canonical transcript 快照(不含 Memory overlay 等临时投影)。"""
        return self._runtime.messages

    @property
    def queued_steering_messages(self) -> tuple[str, ...]:
        return tuple(
            message.text for message in self._runtime.harness.queued_messages.steering
        )

    @property
    def queued_follow_up_messages(self) -> tuple[str, ...]:
        return tuple(
            message.text for message in self._runtime.harness.queued_messages.follow_up
        )

    def queue_update_event(self) -> QueueUpdateEvent:
        """把当前队列状态打包为事件,供前端主动同步。"""
        return QueueUpdateEvent(
            steering=self.queued_steering_messages,
            follow_up=self.queued_follow_up_messages,
        )

    # ─── 运行控制 ────────────────────────────────────────────

    async def prompt(
        self,
        content: str,
        *,
        streaming_behavior: StreamingBehavior | None = None,
    ) -> AsyncIterator[LionSessionEvent]:
        """跑一轮对话,或在运行中把消息入队。

        空闲时:驱动一次完整 ``Agent.chat``(含 Memory 预取、自动压缩、
        Plan 上下文重置续跑),事件按产生顺序流出,结束后发 Settled。
        运行中:``streaming_behavior`` 必填,消息入队并发 ``QueueUpdateEvent``。
        """
        if self.is_running:
            if streaming_behavior is None:
                raise RuntimeError(
                    "会话正在运行;请用 streaming_behavior='steer' 或 "
                    "'follow_up' 将消息入队"
                )
            if streaming_behavior == "steer":
                self._runtime.harness.steer(content)
            else:
                self._runtime.harness.follow_up(content)
            yield self.queue_update_event()
            return

        async for event in self._drive(self._agent.chat(content)):
            yield event

    async def continue_(self) -> AsyncIterator[LionSessionEvent]:
        """不追加用户消息,从当前上下文继续运行。"""
        if self.is_running:
            raise RuntimeError("会话正在运行,无法 continue_")
        async for event in self._drive(self._runtime.continue_()):
            yield event

    def cancel(self) -> None:
        """取消当前一轮:同时中断模型流、工具执行与在途 Memory 预取。"""
        self._agent.abort()

    async def aclose(self) -> None:
        """关闭底层 Agent(落盘会话、回收 Memory 任务与 MCP 连接)。"""
        await self._agent.close()

    # ─── 会话管理 ────────────────────────────────────────────

    async def list_sessions(self) -> list[dict]:
        return await self._agent.list_sessions()

    async def resume(self, session_id: str) -> bool:
        return await self._agent.restore_session_id(session_id)

    async def restore_latest(self) -> bool:
        return await self._agent.restore_latest_session()

    async def new_session(self) -> None:
        await self._agent.clear_history()

    # ─── 压缩 / 用量 ─────────────────────────────────────────

    async def compact(self) -> None:
        await self._agent.compact()

    def token_usage(self) -> dict:
        """累计用量与计费快照(input/output/cache/cost 字段见 Agent)。"""
        return self._agent.get_token_usage()

    # ─── Provider / 模型配置 ─────────────────────────────────

    def get_provider_config(self) -> dict:
        return self._agent.get_api_config()

    def configure_provider(self, **kwargs: Any) -> None:
        """运行时切换模型/凭证,直接透传 Agent.configure_api。"""
        self._agent.configure_api(**kwargs)

    # ─── 技能 / 模板视图(补全与 picker 消费)─────────────────

    @property
    def skills(self) -> tuple[Skill, ...]:
        """用户可调用 Skill 的只读视图;首次访问后缓存(发现要扫盘)。"""
        if self._skills_cache is None:
            from lion_code.skills import discover_skills

            self._skills_cache = tuple(
                Skill(
                    name=definition.name,
                    path=Path(definition.skill_dir) if definition.skill_dir else self.cwd,
                    content=definition.prompt_template,
                    description=definition.description or None,
                )
                for definition in discover_skills()
                if definition.user_invocable
            )
        return self._skills_cache

    @property
    def prompt_templates(self) -> tuple[PromptTemplate, ...]:
        """Prompt template 发现按迁移计划在阶段 4 落地;当前恒为空。"""
        return ()

    # ─── 命令 ────────────────────────────────────────────────

    @property
    def command_registry(self) -> CommandRegistry:
        return self._command_registry

    def handle_command(self, text: str) -> CommandResult:
        return self._command_registry.execute(self, text)

    # ─── Lion 特有交互(权限确认 / Plan 审批)─────────────────

    def set_confirm_fn(
        self, fn: Callable[[str], Awaitable[bool]] | None
    ) -> None:
        self._agent.set_confirm_fn(fn)

    def set_plan_approval_fn(
        self, fn: Callable[[str], Awaitable[dict]] | None
    ) -> None:
        self._agent.set_plan_approval_fn(fn)

    def toggle_plan_mode(self) -> None:
        self._agent.toggle_plan_mode()

    # ─── 事件桥 ──────────────────────────────────────────────

    async def _drive(self, run) -> AsyncIterator[LionSessionEvent]:
        """驱动一个 Agent 协程,把订阅事件转成异步流并补应用级事件。

        队列桥接而非直接 async for:``Agent.chat`` 只消费不产出事件,
        事件从 Harness 订阅侧到达;这里保证「协程结束 + 队列排空」后
        才发 ``AgentSettledEvent``。协程异常在排空后原样抛出(不发 Settled,
        前端以异常路径处理)。
        """
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
        unsubscribe = self._runtime.subscribe(queue.put_nowait)
        task = asyncio.ensure_future(run)
        self._running = True
        try:
            while True:
                get_event = asyncio.ensure_future(queue.get())
                done, _ = await asyncio.wait(
                    {get_event, task}, return_when=asyncio.FIRST_COMPLETED
                )
                if get_event in done:
                    yield self._map_event(get_event.result())
                    continue
                get_event.cancel()
                with suppress(asyncio.CancelledError):
                    await get_event
                break
            while not queue.empty():
                yield self._map_event(queue.get_nowait())
        finally:
            unsubscribe()
            if task.done():
                self._running = False
            else:
                # 前端提前关闭事件流不会取消运行(取消需显式 cancel());
                # 任务真正结束时归位 is_running,并取回异常避免 asyncio 告警。
                task.add_done_callback(self._finalize_orphaned_run)
        # 协程异常(排空事件后)原样上抛;正常结束才算归位。
        task.result()
        yield AgentSettledEvent()

    def _map_event(self, event: AgentEvent) -> LionSessionEvent:
        if isinstance(event, AgentEndEvent):
            return SessionAgentEndEvent(messages=event.messages)
        return event

    def _finalize_orphaned_run(self, task: asyncio.Task[None]) -> None:
        """事件流被提前关闭后,任务真正结束时归位状态并取回异常。"""
        self._running = False
        if not task.cancelled():
            task.exception()
