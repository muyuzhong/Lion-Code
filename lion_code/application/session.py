"""LionCodingSession:面向前端的应用会话门面(阶段 1 最小面)。

职责与边界:

- 对外提供 ``prompt``/``continue_``/``cancel``/``is_running``/``messages``/
  队列快照/``aclose``,事件以 ``AsyncIterator[LionSessionEvent]`` 流出;
- 内部组合现有 ``Agent``(Core Runtime 路径)作为实现细节:Agent 已经
  完成 Provider/ToolRuntime/SessionRecorder/ContextManager
  的组装与每轮编排,本层不重复实现任何 Loop;
- 底层 ``AgentEvent`` 原样透传,唯 ``AgentEndEvent`` 包装为
  ``SessionAgentEndEvent``;一次调用彻底结束后追加 ``AgentSettledEvent``;
- 运行中再次 ``prompt`` 必须显式指定 ``streaming_behavior``,消息进入
  Harness 的 steering / follow-up 队列并发出 ``QueueUpdateEvent``。

``Agent`` 始终提供 Core Runtime；本层不再承担新旧运行时选择。
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from lion_code.core.events import AgentEndEvent, AgentEvent, MessageEndEvent
from lion_code.core.messages import AgentMessage, AssistantMessage

from .commands import CommandRegistry, CommandResult, create_default_command_registry
from .events import (
    AgentSettledEvent,
    AutoRetryEndEvent,
    AutoRetryStartEvent,
    CompactionEndEvent,
    CompactionStartEvent,
    LionSessionEvent,
    QueueUpdateEvent,
    SessionAgentEndEvent,
)
from .ports import CodingSessionBackend, ProviderReadinessPort
from .provider_settings import ModelChoice, load_model_choices, remember_model
from .skills import Skill

if TYPE_CHECKING:
    from lion_code.permission_state import PermissionMode
    from lion_code.usage import UsageSnapshot
type StreamingBehavior = Literal["steer", "follow_up"]

_CONTEXT_OVERFLOW_MARKERS = (
    "context length",
    "context window",
    "context limit",
    "maximum context",
    "max context",
    "input is too long",
    "input length",
    "prompt is too long",
    "too many tokens",
    "token limit",
)


def _is_context_overflow_error(message: AssistantMessage | None) -> bool:
    """只依据 canonical Assistant 错误文本识别上下文溢出。"""

    if message is None or message.stop_reason != "error":
        return False
    normalized = (message.error_message or "").lower()
    return any(marker in normalized for marker in _CONTEXT_OVERFLOW_MARKERS)



class LionCodingSession:
    """前端可消费的 application 会话门面，依赖稳定 backend ports。"""

    def __init__(
        self,
        backend: CodingSessionBackend,
        *,
        terminal_output: bool = False,
    ) -> None:
        self._backend = backend
        self._backend.set_terminal_output(terminal_output)
        self._running = False
        self._command_registry = create_default_command_registry()
        self._skills_cache: tuple[Skill, ...] | None = None

    # ─── 环境 / 身份 ─────────────────────────────────────────

    @property
    def cwd(self) -> Path:
        return self._backend.cwd

    @property
    def model(self) -> str:
        return self._backend.model

    @property
    def provider_name(self) -> str:
        return self._backend.provider_name

    @property
    def permission_mode(self) -> PermissionMode:
        return self._backend.permission_mode

    @property
    def session_id(self) -> str:
        return self._backend.session_id

    @property
    def provider_readiness(self) -> ProviderReadinessPort:
        return self._backend.provider_readiness

    @property
    def api_configured(self) -> bool:
        return self.provider_readiness.ready

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
        """Canonical transcript 快照，不含临时上下文投影。"""
        return self._backend.messages

    @property
    def queued_steering_messages(self) -> tuple[str, ...]:
        return self._backend.queue_snapshot().steering

    @property
    def queued_follow_up_messages(self) -> tuple[str, ...]:
        return self._backend.queue_snapshot().follow_up

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

        空闲时:驱动一次完整 ``Agent.chat``(含自动压缩、Plan 上下文重置续跑),
        事件按产生顺序流出,结束后发 Settled。
        运行中:``streaming_behavior`` 必填,消息入队并发 ``QueueUpdateEvent``。
        """
        if self.is_running:
            if streaming_behavior is None:
                raise RuntimeError(
                    "会话正在运行;请用 streaming_behavior='steer' 或 "
                    "'follow_up' 将消息入队"
                )
            if streaming_behavior == "steer":
                self._backend.steer(content)
            else:
                self._backend.follow_up(content)
            yield self.queue_update_event()
            return

        async for event in self._drive(self._backend.prompt(content)):
            yield event

    async def continue_(self) -> AsyncIterator[LionSessionEvent]:
        """不追加用户消息,从当前上下文继续运行。"""
        if self.is_running:
            raise RuntimeError("会话正在运行,无法 continue_")
        async for event in self._drive(self._backend.continue_()):
            yield event

    def cancel(self) -> None:
        """取消当前一轮:同时中断模型流与工具执行。"""
        self._backend.cancel()

    async def aclose(self) -> None:
        """关闭底层 Agent(落盘会话并回收 Capability 任务)。"""
        await self._backend.aclose()

    # ─── 会话管理 ────────────────────────────────────────────

    async def list_sessions(self) -> list[dict]:
        return await self._backend.list_sessions()

    async def resume(self, session_id: str) -> bool:
        return await self._backend.resume(session_id)

    async def rename_session(self, session_id: str, label: str) -> bool:
        return await self._backend.rename_session(session_id, label)

    async def restore_latest(self) -> bool:
        return await self._backend.restore_latest()

    async def new_session(self) -> None:
        await self._backend.new_session()

    # ─── 压缩 / 用量 ─────────────────────────────────────────

    async def compact(self) -> None:
        await self._backend.compact()

    def token_usage(self) -> UsageSnapshot:
        """返回当前 Agent 的冻结 UsageSnapshot。"""
        return self._backend.token_usage()

    # ─── Provider / 模型配置 ─────────────────────────────────

    def get_provider_config(self) -> dict:
        return self._backend.provider_config()

    def configure_provider(self, **kwargs: Any) -> None:
        """仅在会话空闲时切换模型或凭证。"""
        if self._running:
            raise RuntimeError("会话运行中，无法切换 Provider 或模型")
        self._backend.configure_provider(**kwargs)
        if kwargs.get("model"):
            remember_model(provider=self.provider_name, model=kwargs["model"])

    @property
    def available_model_choices(self) -> tuple[ModelChoice, ...]:
        """picker 候选:当前模型置顶,其余按最近使用排序(本地累积)。"""
        current = ModelChoice(provider_name=self.provider_name, model=self.model)
        return tuple(dict.fromkeys((current, *load_model_choices())))

    def set_model(self, model: str) -> None:
        """切换活动模型(同 provider),并记入已知模型。"""
        self.configure_provider(model=model)

    # ─── Thinking 档位 ───────────────────────────────────────

    @property
    def thinking_level(self) -> str:
        """当前 thinking 档位(off..xhigh)。"""
        return self._backend.thinking_level

    @property
    def available_thinking_levels(self) -> tuple[str, ...]:
        """当前后端支持的 thinking 档位。"""
        return self._backend.available_thinking_levels

    def set_thinking_level(self, level: str) -> str:
        """设定 thinking 档位;返回生效档位(未变也返回当前值)。"""
        if self._running:
            raise RuntimeError("会话运行中，无法切换 thinking 档位")
        return self._backend.set_thinking_level(level)

    def cycle_thinking_level(self) -> str:
        """循环到下一档;返回生效档位。"""
        if self._running:
            raise RuntimeError("会话运行中，无法切换 thinking 档位")
        return self._backend.cycle_thinking_level()

    # ─── 技能 / 模板视图(补全与 picker 消费)─────────────────

    @property
    def skills(self) -> tuple[Skill, ...]:
        """用户可调用 Skill 的只读视图;首次访问后缓存(发现要扫盘)。"""
        if self._skills_cache is None:
            from lion_code.capabilities.skill.discovery import discover_skills

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
        self._backend.set_confirm_fn(fn)

    def set_plan_approval_fn(
        self, fn: Callable[[str], Awaitable[dict]] | None
    ) -> None:
        self._backend.set_plan_approval_fn(fn)

    def set_notice_fn(
        self,
        fn: Callable[[str, Literal["info", "error"]], None] | None,
    ) -> None:
        """把 Agent 的非对话状态交给当前前端实例。"""

        self._backend.set_notice_fn(fn)

    def toggle_plan_mode(self) -> None:
        self._backend.toggle_plan_mode()

    # ─── 事件桥 ──────────────────────────────────────────────
    # 统一承载正常运行与 overflow retry 的事件桥接。

    async def _drive(self, run) -> AsyncIterator[LionSessionEvent]:
        """驱动一个 Agent 协程,把订阅事件转成异步流并补应用级事件。

        队列桥接而非直接 async for:``Agent.chat`` 只消费不产出事件,
        事件从 Harness 订阅侧到达;这里保证「协程结束 + 队列排空」后
        才发 ``AgentSettledEvent``。协程异常在排空后原样抛出(不发 Settled,
        前端以异常路径处理)。
        """
        queue: asyncio.Queue[AgentEvent] = asyncio.Queue()
        unsubscribe = self._backend.subscribe(queue.put_nowait)
        task = asyncio.ensure_future(run)
        retry_started = False
        terminal_assistant: AssistantMessage | None = None
        self._running = True
        try:
            while True:
                terminal_assistant = None
                while True:
                    get_event = asyncio.ensure_future(queue.get())
                    done, _ = await asyncio.wait(
                        {get_event, task}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if get_event in done:
                        event = get_event.result()
                        if isinstance(event, MessageEndEvent) and isinstance(
                            event.message, AssistantMessage
                        ):
                            terminal_assistant = event.message
                        yield self._map_event(
                            event,
                            will_retry=(
                                not retry_started
                                and isinstance(event, AgentEndEvent)
                                and _is_context_overflow_error(terminal_assistant)
                            ),
                        )
                        continue
                    get_event.cancel()
                    with suppress(asyncio.CancelledError):
                        await get_event
                    break
                while not queue.empty():
                    event = queue.get_nowait()
                    if isinstance(event, MessageEndEvent) and isinstance(
                        event.message, AssistantMessage
                    ):
                        terminal_assistant = event.message
                    yield self._map_event(
                        event,
                        will_retry=(
                            not retry_started
                            and isinstance(event, AgentEndEvent)
                            and _is_context_overflow_error(terminal_assistant)
                        ),
                    )

                task.result()
                if retry_started:
                    success = (
                        terminal_assistant is not None
                        and terminal_assistant.stop_reason not in {"error", "aborted"}
                    )
                    final_error = None
                    if not success:
                        final_error = (
                            terminal_assistant.error_message
                            if terminal_assistant is not None
                            else None
                        ) or (
                            terminal_assistant.stop_reason
                            if terminal_assistant is not None
                            else "Provider produced no assistant message"
                        )
                    yield AutoRetryEndEvent(
                        success=success,
                        attempt=1,
                        final_error=final_error,
                    )
                    break

                if not _is_context_overflow_error(terminal_assistant):
                    break

                yield CompactionStartEvent(reason="overflow")
                try:
                    compacted = await self._backend.compact_for_overflow()
                except asyncio.CancelledError:
                    yield CompactionEndEvent(
                        reason="overflow",
                        aborted=True,
                        will_retry=False,
                    )
                    break
                except Exception as exc:  # 自动恢复失败不能遮蔽原始 overflow
                    yield CompactionEndEvent(
                        reason="overflow",
                        aborted=True,
                        will_retry=False,
                        error_message=str(exc) or exc.__class__.__name__,
                    )
                    break

                if not compacted:
                    yield CompactionEndEvent(
                        reason="overflow",
                        aborted=True,
                        will_retry=False,
                        error_message="没有可安全压缩的旧上下文",
                    )
                    break

                if self._backend.cancelled:
                    yield CompactionEndEvent(
                        reason="overflow",
                        aborted=True,
                        will_retry=False,
                    )
                    break

                yield CompactionEndEvent(
                    reason="overflow",
                    aborted=False,
                    will_retry=True,
                )

                retry_started = True
                yield AutoRetryStartEvent(
                    attempt=1,
                    max_attempts=1,
                    delay_ms=0,
                    error_message=getattr(terminal_assistant, "error_message", None)
                    or "Context overflow",
                )
                if self._backend.cancelled:
                    yield AutoRetryEndEvent(
                        success=False,
                        attempt=1,
                        final_error="aborted",
                    )
                    break
                task = asyncio.ensure_future(self._backend.continue_())
        finally:
            unsubscribe()
            if task.done():
                self._running = False
            else:
                # 前端提前关闭事件流不会取消运行(取消需显式 cancel());
                # 任务真正结束时归位 is_running,并取回异常避免 asyncio 告警。
                task.add_done_callback(self._finalize_orphaned_run)
        yield AgentSettledEvent()

    def _map_event(
        self,
        event: AgentEvent,
        *,
        will_retry: bool = False,
    ) -> LionSessionEvent:
        if isinstance(event, AgentEndEvent):
            return SessionAgentEndEvent(
                will_retry=will_retry,
            )
        return event

    def _finalize_orphaned_run(self, task: asyncio.Task[None]) -> None:
        """事件流被提前关闭后,任务真正结束时归位状态并取回异常。"""
        self._running = False
        if not task.cancelled():
            task.exception()

    def get_egress_config(self) -> list[str]:
        """返回 tooling 管理的当前 Egress 白名单配置。"""

        return self._backend.egress_hosts()

    def configure_egress(self, allow_hosts: Sequence[str]) -> list[str]:
        """在会话空闲时更新 tooling 管理的 Egress 白名单。"""

        if self._running:
            raise RuntimeError("会话运行中，无法修改 Egress 白名单")
        return self._backend.configure_egress(allow_hosts)
