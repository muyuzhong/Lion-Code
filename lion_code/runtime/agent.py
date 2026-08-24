"""AgentRuntime：一次 Agent operation 中各 Runtime Owner 的调用顺序编排。

AgentRuntime 不拥有 Provider/Context/Session 的任何 mutable 状态，也不感知
ProviderController。它只按固定顺序调用三个 Owner，并把 Core 终态投影为对外结果：

- SessionRuntime.ensure_ready → ContextRuntime.prepare/compact →
  ConversationRuntime.prompt → 结果投影。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from ..core.events import (
    CompactionCompletedEvent,
    CompactionStartedEvent,
    MessageEndEvent,
    MessageStartEvent,
)
from ..core.messages import AssistantMessage, TextContent, UserMessage
from ..observers import TerminalRenderer, UsageObserver
from ..usage import BudgetPolicy, UsageLedger
from .context import ContextRuntime
from .conversation import ConversationRuntime
from .execution import ExecutionControl
from .session import SessionRestoreState, SessionRuntime

StopReason = Literal[
    "completed",
    "max_turns",
    "max_cost",
    "timeout",
    "model_error",
    "tool_error",
    "aborted",
]


@dataclass(slots=True)
class AgentRunResult:
    """一次 Agent 运行的结构化结果，供非终端消费者读取。"""

    session_id: str
    final_text: str
    stop_reason: str
    turns: int
    wall_time_seconds: float
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_usd: float
    error: str | None = None


def _recent_context_boundary(
    messages: tuple[Any, ...],
    *,
    keep_user_boundaries: int = 1,
) -> int:
    """按用户消息边界保留最近轮次，避免拆开 ToolCall 与 ToolResult。"""

    found = 0
    for index in range(len(messages) - 1, -1, -1):
        if not isinstance(messages[index], UserMessage):
            continue
        found += 1
        if found == keep_user_boundaries:
            return index
    return len(messages)


class RuntimeIdentityHost(Protocol):
    """AgentRuntime 编排所需的宿主边界：API 就绪态、终端渲染与通知。"""

    _terminal_output: bool

    @property
    def api_configured(self) -> bool: ...

    def _create_terminal_renderer(self) -> TerminalRenderer: ...

    def _emit_notice(
        self,
        message: str,
        *,
        role: Literal["info", "error"] = "info",
    ) -> None: ...


class AgentRuntime:
    """只负责编排一次 Agent operation 如何按顺序调用三个 Runtime Owner。"""

    def __init__(
        self,
        *,
        conversation: ConversationRuntime,
        session: SessionRuntime,
        context: ContextRuntime,
        identity: RuntimeIdentityHost,
        execution: ExecutionControl,
        usage: UsageLedger,
        budget: BudgetPolicy,
    ) -> None:
        self._conversation = conversation
        self._session = session
        self._context = context
        self._identity = identity
        self._execution = execution
        self._usage = usage
        self._budget = budget
        self._last_stop_reason: str | None = None
        self._observer_unsubscribers: list[Any] = []
        self._terminal_renderer: TerminalRenderer | None = None
        self._terminal_renderer_unsubscribe: Any = None
        self._usage_observer: UsageObserver | None = None
        conversation.bind_before_tool_calls(self.before_core_tool_calls)
        self.reset_observers()

    @property
    def conversation(self) -> ConversationRuntime:
        return self._conversation

    @property
    def session(self) -> SessionRuntime:
        return self._session

    @property
    def context(self) -> ContextRuntime:
        return self._context

    @property
    def execution(self) -> ExecutionControl:
        return self._execution

    @property
    def last_stop_reason(self) -> str | None:
        return self._last_stop_reason

    @last_stop_reason.setter
    def last_stop_reason(self, value: str | None) -> None:
        self._last_stop_reason = value

    # ─── 状态边界收敛 ─────────────────────────────────────────

    async def ensure_ready(self) -> None:
        """收敛后台清理、解析模型限制并恢复 Recorder 写入位置。"""

        await self._conversation.flush_background_operations()
        await self._context.resolve_model_limits(
            self._conversation.provider,
            self._conversation.model,
        )
        await self._session.ensure_ready()

    def reset_observers(self) -> None:
        """按 Usage -> Session -> Renderer -> capture 的稳定顺序重建观察器。"""

        identity = self._identity
        for unsubscribe in self._observer_unsubscribers:
            unsubscribe()
        self._observer_unsubscribers.clear()
        self._terminal_renderer_unsubscribe = None
        self._terminal_renderer = (
            identity._create_terminal_renderer() if identity._terminal_output else None
        )
        self._usage_observer = UsageObserver(self._usage)
        self._observer_unsubscribers.append(
            self._conversation.subscribe(self._usage_observer.handle)
        )
        if self._session.recorder is not None:
            self._observer_unsubscribers.append(
                self._conversation.subscribe(self._session.recorder.handle)
            )
        if self._terminal_renderer is not None:
            self._terminal_renderer_unsubscribe = self._conversation.subscribe(
                self._terminal_renderer.handle
            )
            self._observer_unsubscribers.append(self._terminal_renderer_unsubscribe)
        self._observer_unsubscribers.append(
            self._conversation.subscribe(self._conversation.capture_event)
        )

    def reset_session_usage(self) -> None:
        self._usage.reset()
        self._last_stop_reason = None

    # ─── Kernel 工具边界钩子与终态投影 ────────────────────────

    def before_core_tool_calls(self, _assistant: AssistantMessage) -> str | None:
        """在工具调用前记录 turn，并用同一 BudgetPolicy 检查累计用量。"""

        self._usage.record_turn()
        decision = self._budget.check(self._usage.snapshot())
        if not decision.exceeded:
            return None
        self._last_stop_reason = decision.kind
        try:
            self._identity._emit_notice(f"Budget exceeded: {decision.reason}")
        except UnicodeError:
            pass
        return decision.reason

    def sync_conversation_outcome(self) -> None:
        """把 Core 的 canonical 终态映射回对外 stop reason。"""

        assistant = self._conversation.last_assistant()
        if assistant is None:
            return
        if self._execution.cancelled or assistant.stop_reason == "aborted":
            self._execution.cancel()
            self._last_stop_reason = "aborted"
        elif assistant.stop_reason == "error":
            self._last_stop_reason = "model_error"
        elif self._last_stop_reason is None:
            self._last_stop_reason = "completed"

    # ─── 会话操作：new / restore / compact ───────────────────

    async def new_session(self, *, model: str, thinking_level: str) -> None:
        """结束当前会话并创建新 Session；旧 append-only 历史保持可恢复。"""

        await self._session.new_session(model=model, thinking_level=thinking_level)
        self._context.on_session_reset()
        await self._conversation.replace_active_context([])
        self.reset_observers()
        await self.ensure_ready()
        self.reset_session_usage()
        self._identity._emit_notice("Conversation cleared.")

    async def restore(self, state: SessionRestoreState) -> bool:
        """回放恢复快照到唯一活跃上下文；配置恢复由上层 facade 先行完成。"""

        await self._activate_session(state)
        self._identity._emit_notice(
            f"Session restored ({len(state.messages)} messages)."
        )
        return True

    async def _activate_session(self, state: SessionRestoreState) -> None:
        """切换会话身份并回放其 canonical messages 到唯一活跃上下文。"""

        await self._session.restore(
            state,
            model=state.model or self._conversation.model,
        )
        self._context.on_session_reset()
        await self._conversation.replace_active_context(state.messages)
        self.reset_observers()
        await self.ensure_ready()
        self.reset_session_usage()

    async def compact(self) -> None:
        await self.ensure_ready()
        if await self.compact_if_needed(force=True, reason="manual"):
            self._identity._emit_notice("Conversation compacted.")

    async def compact_if_needed(
        self,
        *,
        force: bool = False,
        keep_user_boundaries: int = 1,
        reason: Literal["threshold", "overflow", "manual"] = "threshold",
        objective: str | None = None,
    ) -> bool:
        """在新用户轮次前写入 CompactionEntry 并回放唯一活跃上下文。"""

        if self._session.recorder is None or self._context.context_compactor is None:
            return False
        if not force and not self._context.should_compact_now():
            return False

        messages = self._conversation.messages
        entry_ids = await self._session.context_entry_ids()
        if len(entry_ids) != len(messages):
            raise RuntimeError("Session context does not match active Harness messages")

        boundary = _recent_context_boundary(
            messages,
            keep_user_boundaries=keep_user_boundaries,
        )
        replaced_ids = list(entry_ids[:boundary])
        summary_messages = tuple(messages[:boundary])
        recent_context = tuple(messages[boundary:])
        if not replaced_ids:
            if force:
                return False
            replaced_ids = list(entry_ids)
            summary_messages = messages
            recent_context = ()
        if not replaced_ids:
            return False

        await self._conversation.emit(CompactionStartedEvent(reason=reason))
        try:
            summary = await self._context.summarize(
                summary_messages,
                recent_context=recent_context,
                objective=objective,
            )
            await self._session.record_compaction(
                summary=summary,
                replaces_entry_ids=replaced_ids,
            )
            state = await self._session.load(self._session.state.id)
            if state is None:
                raise RuntimeError("Session disappeared after compaction")
            await self._conversation.replace_active_context(state.messages)
            self._usage.reset_context_tracking()
            self._context.on_compacted()
        except asyncio.CancelledError:
            await self._conversation.emit(
                CompactionCompletedEvent(reason=reason, aborted=True)
            )
            raise
        await self._conversation.emit(CompactionCompletedEvent(reason=reason))
        return True

    async def compact_for_overflow(self) -> bool:
        """强制压缩旧上下文，保留最近成功轮次和当前失败 prompt。"""

        return await self.compact_if_needed(
            force=True,
            keep_user_boundaries=2,
            reason="overflow",
        )

    # ─── run 编排 ─────────────────────────────────────────────

    async def chat(self, user_message: str) -> None:
        """执行一次完整用户轮，保持 Session/Context/Core 的既有时序。"""

        self._execution.begin()
        self._last_stop_reason = None
        if not self._identity.api_configured:
            # 未配置凭证不再静默返回：向订阅者产出一条含说明的 error 消息，
            # 让桌面/REST 前端看到明确的失败反馈（而不只是被忽略的 notice）。
            error_message = (
                "API 未配置：设置 ANTHROPIC_API_KEY / OPENAI_API_KEY(+OPENAI_BASE_URL)，"
                "或在设置面板中配置 Provider 与模型。"
            )
            message = AssistantMessage(
                model=self._conversation.model,
                content=[TextContent(text=error_message)],
                stop_reason="error",
                error_message=error_message,
            )
            await self._conversation.emit(MessageStartEvent(message=message))
            self._conversation.harness.append_message(message)
            await self._conversation.emit(MessageEndEvent(message=message))
            self._identity._emit_notice(error_message, role="error")
            return
        await self.ensure_ready()
        if self._execution.cancelled:
            return
        await self.compact_if_needed(objective=user_message)
        if self._execution.cancelled:
            return
        await self._conversation.prompt(user_message)
        self.sync_conversation_outcome()
        self._context.evaluate_compaction_required()

    async def run_once(self, prompt: str) -> dict[str, Any]:
        """运行一次并返回捕获的文本与本次 token 差值。"""

        self._conversation.begin_run_capture()
        before = self._usage.snapshot()
        try:
            await self.chat(prompt)
        finally:
            text = self._conversation.end_run_capture()
        after = self._usage.snapshot()
        return {
            "text": text,
            "tokens": {
                "input": after.input_tokens - before.input_tokens,
                "output": after.output_tokens - before.output_tokens,
            },
        }

    async def run(
        self,
        prompt: str,
        *,
        timeout: float | None = None,
    ) -> AgentRunResult:
        """执行一次并把取消、超时和 Provider 异常投影为结构化结果。"""

        before = self._usage.snapshot()
        start = time.monotonic()
        self._conversation.begin_run_capture()
        timed_out = False
        timeout_handle = None
        run_task = asyncio.current_task()
        if timeout is not None:
            loop = asyncio.get_running_loop()

            def on_timeout() -> None:
                nonlocal timed_out
                timed_out = True
                self.abort()
                if run_task is not None and not run_task.done():
                    run_task.cancel()

            timeout_handle = loop.call_later(timeout, on_timeout)

        stop_reason = "completed"
        error: str | None = None
        try:
            await self.chat(prompt)
            stop_reason = self._last_stop_reason or "completed"
            if stop_reason == "model_error":
                assistant = self._conversation.last_assistant()
                error = (
                    assistant.error_message
                    if assistant is not None and assistant.error_message
                    else "Provider error"
                )
        except asyncio.CancelledError:
            self.abort()
            stop_reason = "aborted"
        except Exception as exc:
            stop_reason = "model_error"
            error = str(exc) or exc.__class__.__name__
        finally:
            if timeout_handle is not None:
                timeout_handle.cancel()
            final_text = self._conversation.end_run_capture()

        if timed_out:
            stop_reason = "timeout"
            error = error or f"timeout after {timeout}s"
        after = self._usage.snapshot()
        return AgentRunResult(
            session_id=self._session.state.id,
            final_text=final_text,
            stop_reason=stop_reason,
            turns=after.turns - before.turns,
            wall_time_seconds=time.monotonic() - start,
            input_tokens=after.input_tokens - before.input_tokens,
            output_tokens=after.output_tokens - before.output_tokens,
            cache_read_tokens=after.cache_read_tokens - before.cache_read_tokens,
            cost_usd=after.cost_usd - before.cost_usd,
            error=error,
        )

    # ─── 终端观察器与中止 ─────────────────────────────────────

    def set_terminal_output(self, enabled: bool) -> None:
        """切换终端观察器，绝不重建 UsageObserver 或 SessionRecorder。"""

        identity = self._identity
        if enabled == identity._terminal_output:
            return
        if self._conversation.is_running:
            raise RuntimeError("Agent 运行中，无法切换终端输出")
        if enabled:
            identity._terminal_output = True
            self._terminal_renderer = identity._create_terminal_renderer()
            self._terminal_renderer_unsubscribe = self._conversation.subscribe(
                self._terminal_renderer.handle
            )
            self._observer_unsubscribers.append(self._terminal_renderer_unsubscribe)
            return
        unsubscribe = self._terminal_renderer_unsubscribe
        if unsubscribe is not None:
            unsubscribe()
            self._observer_unsubscribers.remove(unsubscribe)
        self._terminal_renderer_unsubscribe = None
        self._terminal_renderer = None
        identity._terminal_output = False

    def abort(self) -> None:
        """同时取消 Core 流和可能在运行的压缩任务。"""

        self._execution.cancel()
        self._last_stop_reason = "aborted"
        self._context.cancel_pending_compaction()

    async def close(self) -> None:
        """按既有 finally 链回收后台任务、Provider 与 Capability 资源。"""

        try:
            await self._conversation.flush_background_operations()
        finally:
            try:
                await self._session.close()
            finally:
                await self._conversation.aclose()
