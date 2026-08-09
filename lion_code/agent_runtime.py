"""Core Agent Runtime 的组装与单会话协调。

组装关系：

- ``get_system`` -- 动态读取 Plan/Skill 之后的系统提示；
- ``get_tools`` -- 每轮读取当前 Registry 激活的工具；
- ``prepare_context`` -- 后续接入 Lion Context Manager；
- ``ToolRuntime`` -- 权限、Hook、新鲜度、持久化、审计等中间件。

Core 在每轮调用模型前会重新执行 ``get_tools``、``get_system`` 与
``prepare_context``，因此本运行时不缓存这些值。权限与结果策略完全由
ToolRuntime 的中间件负责，运行时不再额外注入 ``before_tool_call`` /
``after_tool_call``。
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from lion_code.adapters import adapt_active_tools
from lion_code.context import (
    ContextCompactor,
    ContextManager,
    ContextRuntimeState,
    ModelLimitsResolver,
    ProviderContextCompactor,
    effective_window_tokens,
)
from lion_code.core import (
    AgentHarness,
    AgentHarnessConfig,
    AgentMessage,
    EventListener,
)
from lion_code.core.cancellation import CancellationView
from lion_code.core.events import AgentEvent, MessageEndEvent, MessageUpdateEvent
from lion_code.core.loop import BeforeToolCalls, PrepareContext
from lion_code.core.messages import AssistantMessage, UserMessage
from lion_code.core.provider import ModelProvider
from lion_code.core.provider_events import TextDeltaEvent
from lion_code.execution_control import ExecutionControl
from lion_code.memory_runtime import (
    MemoryContextInjector,
    MemoryInjectionReport,
    MemoryOverlay,
    ReadOnlyMessageSource,
)
from lion_code.observers import TerminalRenderer, UsageObserver
from lion_code.permission_state import PermissionMode
from lion_code.providers.thinking import ThinkingLevel
from lion_code.session_identity import SessionIdentityState
from lion_code.session_lifecycle import SessionLifecycle
from lion_code.session_runtime import SessionRecorder, SessionRepository
from lion_code.tooling import ToolRuntime

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
    messages: tuple[AgentMessage, ...],
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


class LionAgentRuntime(ReadOnlyMessageSource):
    """组装 Provider + Core Harness + ToolRuntime 的应用运行时。"""

    def __init__(
        self,
        *,
        provider: ModelProvider,
        model: str,
        get_system: Callable[[], str],
        tool_runtime: ToolRuntime,
        cancellation: CancellationView | None = None,
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
            ),
            cancellation=cancellation,
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

    def replace_provider(self, provider: ModelProvider) -> ModelProvider:
        """热替换后续 Provider 请求使用的 provider,返回旧 provider。

        与 ``set_model`` 同理:Harness 每轮 live 读取 ``config.provider``,
        故直接改 live 配置即生效。旧 provider 的连接资源由调用方负责回收
        (Agent 用 ``_schedule_background_operation`` 排程其 ``aclose``)。
        """
        previous = self._provider
        self._provider = provider
        self.harness.config.provider = provider
        return previous

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

    async def aclose(self) -> None:
        """关闭由 Provider 持有的连接资源。"""
        close = getattr(self._provider, "aclose", None)
        if close is not None:
            await close()

    @property
    def messages(self) -> tuple[AgentMessage, ...]:
        """返回当前对话的消息快照。"""
        return self.harness.messages


# ─── 窄端口：按 coordinator 实际访问模式分组 ──────────────────


class UsageStateHost(Protocol):
    """Token 计数与预算检查所需的宿主边界。"""

    effective_window: int
    total_input_tokens: int
    total_output_tokens: int
    total_cache_read_tokens: int
    total_cache_creation_tokens: int
    last_input_token_count: int
    current_turns: int
    last_api_call_time: float

    def _check_budget(self) -> dict[str, Any]: ...

    def _get_current_cost_usd(self) -> float: ...


class RuntimeIdentityHost(Protocol):
    """模型标识、终端渲染与中止/通知所需的宿主边界。"""

    model: str
    is_sub_agent: bool
    _thinking_level: ThinkingLevel
    _terminal_output: bool
    _system_prompt: str
    _last_stop_reason: str | None

    @property
    def api_configured(self) -> bool: ...

    @property
    def is_aborted(self) -> bool: ...

    def _create_terminal_renderer(self) -> TerminalRenderer: ...

    def _emit_notice(
        self,
        message: str,
        *,
        role: Literal["info", "error"] = "info",
    ) -> None: ...

    def _apply_core_thinking_level(self, level: ThinkingLevel) -> None: ...

    async def _ensure_mcp_tools(self) -> None: ...


class SessionStateHost(Protocol):
    """会话标识、仓库、Plan 模式与工具环境所需的宿主边界。"""

    _plan_file_path: str | None
    _pending_core_context_reset: str | None
    _base_system_prompt: str
    _session_repository: SessionRepository
    tool_context: Any
    tool_environment: Any

    @property
    def session_state(self) -> SessionIdentityState: ...

    @property
    def permission_mode(self) -> PermissionMode: ...

    def _generate_plan_file_path(self) -> str: ...

    def _build_plan_mode_prompt(self) -> str: ...


class MemoryTurnHost(Protocol):
    """Memory 注入、Overlay 与轮次快照所需的宿主边界。"""

    _memory_coordinator: Any
    _turn_memory_overlays: tuple[MemoryOverlay, ...]
    _last_memory_injection: MemoryInjectionReport

    @property
    def _memory_injector(self) -> MemoryContextInjector: ...

    def _prepare_turn_memory_snapshot(self, user_message: str) -> None: ...

    def _build_turn_memory_overlays(self) -> tuple[MemoryOverlay, ...]: ...

    async def _update_session_memory_after_turn(
        self,
        user_message: str,
        turn_start_index: int,
    ) -> None: ...

    def _reload_project_memory(self) -> None: ...

    def _reload_session_memory(self) -> None: ...


def sync_usage_from_observer(
    host: UsageStateHost,
    observer: UsageObserver | None,
    *,
    last_synced_response_count: int,
) -> int:
    """把 UsageObserver 的累计统计投影到宿主，并返回最新响应序号。"""

    if observer is None:
        return last_synced_response_count
    totals = observer.totals
    host.total_input_tokens = totals.input_tokens
    host.total_output_tokens = totals.output_tokens
    host.total_cache_read_tokens = totals.cache_read_tokens
    host.total_cache_creation_tokens = totals.cache_write_tokens
    last = observer.last_usage
    response_count = observer.response_count
    if response_count == last_synced_response_count:
        return last_synced_response_count
    if last is None:
        host.last_input_token_count = 0
    elif last.total_tokens:
        host.last_input_token_count = last.total_tokens
    else:
        host.last_input_token_count = (
            last.input + last.cache_read + last.cache_write + last.output
        )
    if observer.last_response_at is not None:
        host.last_api_call_time = observer.last_response_at
    return response_count


class AgentRuntimeCoordinator:
    """拥有一个 Agent 的 Core 生命周期，但不反向依赖 Agent 实现。

    通过四个窄端口访问宿主能力，不再依赖单个宽协议：
    - ``usage`` -- token 计数与预算检查
    - ``identity`` -- 模型标识、终端渲染、中止/通知与 MCP 初始化
    - ``session`` -- 会话标识、仓库、Plan 模式与工具环境
    - ``memory`` -- Memory 注入、Overlay 与轮次快照
    """

    def __init__(
        self,
        *,
        usage: UsageStateHost,
        identity: RuntimeIdentityHost,
        session: SessionStateHost,
        memory: MemoryTurnHost,
        execution: ExecutionControl,
        provider: ModelProvider,
        model: str,
        tool_runtime: ToolRuntime,
        context_manager: ContextManager,
        context_compactor: ContextCompactor | None,
        model_limits_resolver: ModelLimitsResolver,
    ) -> None:
        self._usage = usage
        self._identity = identity
        self._session = session
        self._memory = memory
        self._execution = execution
        self._context_manager = context_manager
        self._context_compactor = context_compactor
        self._model_limits_resolver = model_limits_resolver
        self._resolved_model_limits_for: tuple[int, str] | None = None
        self._core_compaction_required = False
        self._last_context_actions: tuple[Any, ...] = ()
        self._core_compaction_task: asyncio.Task[str] | None = None
        self._background_tasks: set[asyncio.Task[object]] = set()
        self._background_errors: list[BaseException] = []
        self._output_buffer: list[str] | None = None
        self._captured_assistant_text: str | None = None
        self._last_synced_core_response_count = 0
        self._terminal_renderer: TerminalRenderer | None = None
        self._terminal_renderer_unsubscribe: Callable[[], None] | None = None
        self._usage_observer: UsageObserver | None = None
        self._session_recorder: SessionRecorder | None = None
        self._observer_unsubscribers: list[Callable[[], None]] = []
        self._runtime = LionAgentRuntime(
            provider=provider,
            model=model,
            get_system=lambda: self._identity._system_prompt,
            tool_runtime=tool_runtime,
            cancellation=execution.cancellation,
            prepare_context=self.prepare_core_context,
            before_tool_calls=self.before_core_tool_calls,
        )
        if self._context_compactor is None:
            self._context_compactor = ProviderContextCompactor(
                provider=provider,
                get_model=lambda: self._identity.model,
            )
        self._session_lifecycle = SessionLifecycle(self)
        self.reset_core_observers()

    @property
    def core_runtime(self) -> LionAgentRuntime:
        """返回唯一持有活跃 Provider 与 canonical messages 的 Core Runtime。"""

        return self._runtime

    @core_runtime.setter
    def core_runtime(self, value: LionAgentRuntime) -> None:
        self._runtime = value

    @property
    def execution(self) -> ExecutionControl:
        return self._execution

    @property
    def session_recorder(self) -> SessionRecorder | None:
        return self._session_recorder

    @session_recorder.setter
    def session_recorder(self, value: SessionRecorder | None) -> None:
        self._session_recorder = value

    @property
    def context_compactor(self) -> ContextCompactor | None:
        return self._context_compactor

    @context_compactor.setter
    def context_compactor(self, value: ContextCompactor | None) -> None:
        self._context_compactor = value

    @property
    def context_manager(self) -> ContextManager:
        return self._context_manager

    @property
    def resolved_model_limits_for(self) -> tuple[int, str] | None:
        return self._resolved_model_limits_for

    @resolved_model_limits_for.setter
    def resolved_model_limits_for(self, value: tuple[int, str] | None) -> None:
        self._resolved_model_limits_for = value

    @property
    def core_compaction_required(self) -> bool:
        return self._core_compaction_required

    @core_compaction_required.setter
    def core_compaction_required(self, value: bool) -> None:
        self._core_compaction_required = value

    @property
    def usage_observer(self) -> UsageObserver | None:
        return self._usage_observer

    @usage_observer.setter
    def usage_observer(self, value: UsageObserver | None) -> None:
        self._usage_observer = value

    @property
    def terminal_renderer(self) -> TerminalRenderer | None:
        return self._terminal_renderer

    @property
    def session_lifecycle(self) -> SessionLifecycle:
        """返回拥有 clear/restore/compact/close 的会话生命周期协调器。"""
        return self._session_lifecycle

    async def prepare_core_context(
        self, messages: list[AgentMessage]
    ) -> list[AgentMessage]:
        """只生成 Provider 投影，不改写 canonical history 或 JSONL。"""

        self.sync_core_usage()
        state = self.context_runtime_state()
        prepared = self._context_manager.prepare(messages, state)
        projected, memory_report = self._memory._memory_injector.inject(
            tuple(prepared.messages),
            self._memory._turn_memory_overlays,
            max_tokens=state.effective_window_tokens,
        )
        self._last_context_actions = prepared.actions
        self._memory._last_memory_injection = memory_report
        self._core_compaction_required = prepared.compaction_required
        return projected

    async def capture_core_text(self, event: AgentEvent) -> None:
        """为 run_once/run 捕获本次助手文本，不参与终端或 TUI 渲染。"""

        if self._output_buffer is None:
            return
        if isinstance(event, MessageUpdateEvent) and isinstance(
            event.assistant_message_event, TextDeltaEvent
        ):
            self._output_buffer.append(event.assistant_message_event.delta)
        elif isinstance(event, MessageEndEvent) and isinstance(
            event.message, AssistantMessage
        ):
            self._captured_assistant_text = event.message.text

    def sync_core_usage(self) -> None:
        self._last_synced_core_response_count = sync_usage_from_observer(
            self._usage,
            self._usage_observer,
            last_synced_response_count=self._last_synced_core_response_count,
        )

    def last_core_assistant(self) -> AssistantMessage | None:
        return next(
            (
                message
                for message in reversed(self._runtime.messages)
                if isinstance(message, AssistantMessage)
            ),
            None,
        )

    def sync_core_outcome(self) -> None:
        """把 Core 的 canonical 终态映射回 Agent 对外状态。"""

        assistant = self.last_core_assistant()
        if assistant is None:
            return
        identity = self._identity
        if self._execution.cancelled or assistant.stop_reason == "aborted":
            self._execution.cancel()
            identity._last_stop_reason = "aborted"
        elif assistant.stop_reason == "error":
            identity._last_stop_reason = "model_error"
        elif identity._last_stop_reason is None:
            identity._last_stop_reason = "completed"

    def before_core_tool_calls(self, _assistant: AssistantMessage) -> str | None:
        """在工具调用前同步用量、递增轮次并检查既有预算。"""

        self.sync_core_usage()
        self._usage.current_turns += 1
        budget = self._usage._check_budget()
        if not budget["exceeded"]:
            return None
        self._identity._last_stop_reason = budget["kind"]
        try:
            self._identity._emit_notice(f"Budget exceeded: {budget['reason']}")
        except UnicodeError:
            pass
        return budget["reason"]

    def reset_session_counters(self) -> None:
        usage = self._usage
        identity = self._identity
        usage.total_input_tokens = 0
        usage.total_output_tokens = 0
        usage.total_cache_read_tokens = 0
        usage.total_cache_creation_tokens = 0
        usage.last_input_token_count = 0
        usage.current_turns = 0
        usage.last_api_call_time = 0.0
        self._last_synced_core_response_count = (
            self._usage_observer.response_count
            if self._usage_observer is not None
            else 0
        )
        identity._last_stop_reason = None

    def reset_core_observers(self) -> None:
        """按 Usage -> Session -> Renderer -> capture 的稳定顺序重建观察器。"""

        identity = self._identity
        session = self._session
        for unsubscribe in self._observer_unsubscribers:
            unsubscribe()
        self._observer_unsubscribers.clear()
        self._terminal_renderer_unsubscribe = None
        self._terminal_renderer = (
            identity._create_terminal_renderer() if identity._terminal_output else None
        )
        self._usage_observer = UsageObserver()
        self._last_synced_core_response_count = 0
        if identity.is_sub_agent:
            self._session_recorder = None
        else:
            self._session_recorder = SessionRecorder(
                session_id=session.session_state.id,
                model=identity.model,
                thinking_level=identity._thinking_level,
                cwd=session.tool_context.cwd,
                storage=session._session_repository.storage_for(
                    session.session_state.id
                ),
            )
        self._observer_unsubscribers.append(
            self._runtime.subscribe(self._usage_observer.handle)
        )
        if self._session_recorder is not None:
            self._observer_unsubscribers.append(
                self._runtime.subscribe(self._session_recorder.handle)
            )
        if self._terminal_renderer is not None:
            self._terminal_renderer_unsubscribe = self._runtime.subscribe(
                self._terminal_renderer.handle
            )
            self._observer_unsubscribers.append(self._terminal_renderer_unsubscribe)
        self._observer_unsubscribers.append(
            self._runtime.subscribe(self.capture_core_text)
        )

    async def ensure_core_session_ready(self) -> None:
        await self.flush_background_operations()
        await self.resolve_core_model_limits()
        if self._session_recorder is not None:
            await self._session_recorder.initialize()

    async def resolve_core_model_limits(self) -> None:
        key = (id(self._runtime.provider), self._identity.model)
        if self._resolved_model_limits_for == key:
            return
        limits = await self._model_limits_resolver.resolve(
            self._runtime.provider,
            self._identity.model,
        )
        self._usage.effective_window = effective_window_tokens(limits)
        self._resolved_model_limits_for = key

    def context_runtime_state(self) -> ContextRuntimeState:
        usage = self._usage
        return ContextRuntimeState(
            effective_window_tokens=usage.effective_window,
            last_prompt_tokens=usage.last_input_token_count,
            last_model_call_at=usage.last_api_call_time or None,
            now=time.time(),
        )

    async def compact_core_context_if_needed(
        self,
        *,
        force: bool = False,
        keep_user_boundaries: int = 1,
    ) -> bool:
        """在新用户轮次前写入 CompactionEntry 并回放唯一活跃上下文。"""

        if self._session_recorder is None or self._context_compactor is None:
            return False
        self.sync_core_usage()
        if not force and not self._context_manager.should_compact(
            self.context_runtime_state()
        ):
            return False

        messages = self._runtime.messages
        entry_ids = await self._session_recorder.context_entry_ids()
        if len(entry_ids) != len(messages):
            raise RuntimeError("Session context does not match active Harness messages")

        boundary = _recent_context_boundary(
            messages,
            keep_user_boundaries=keep_user_boundaries,
        )
        replaced_ids = list(entry_ids[:boundary])
        summary_messages = tuple(messages[:boundary])
        if not replaced_ids:
            if force:
                return False
            replaced_ids = list(entry_ids)
            summary_messages = messages
        if not replaced_ids:
            return False

        if self._execution.cancelled:
            raise asyncio.CancelledError
        task = asyncio.create_task(self._context_compactor.summarize(summary_messages))
        self._core_compaction_task = task
        try:
            summary = await task
        finally:
            if self._core_compaction_task is task:
                self._core_compaction_task = None
        if self._execution.cancelled:
            raise asyncio.CancelledError
        await self._session_recorder.record_compaction(
            summary=summary,
            replaces_entry_ids=replaced_ids,
        )
        state = await self._session._session_repository.load(
            self._session.session_state.id
        )
        if state is None:
            raise RuntimeError("Session disappeared after compaction")
        await self._runtime.replace_active_context(state.messages)
        self._usage.last_input_token_count = 0
        self._last_context_actions = ()
        self._core_compaction_required = False
        return True

    async def compact_core_context_for_overflow(self) -> bool:
        """强制压缩旧上下文，保留最近成功轮次和当前失败 prompt。"""

        return await self.compact_core_context_if_needed(
            force=True,
            keep_user_boundaries=2,
        )

    async def apply_pending_core_context_reset(self) -> bool:
        """把 Plan 批准摘要持久化后作为唯一活跃上下文继续运行。"""

        session = self._session
        summary = session._pending_core_context_reset
        if summary is None or self._session_recorder is None:
            return False
        replaced_ids = list(await self._session_recorder.context_entry_ids())
        await self._session_recorder.record_compaction(
            summary=summary,
            replaces_entry_ids=replaced_ids,
        )
        state = await session._session_repository.load(session.session_state.id)
        if state is None or len(state.messages) != 1:
            raise RuntimeError(
                "Compaction replay did not produce one active context message"
            )
        active_message = state.messages[0]
        if not isinstance(active_message, UserMessage):
            raise RuntimeError(
                "Compaction replay did not produce one active context message"
            )
        await self._runtime.reset_active_context(active_message.text)
        self.sync_core_usage()
        self._usage.last_input_token_count = 0
        self._last_context_actions = ()
        self._core_compaction_required = False
        session._pending_core_context_reset = None
        return True

    def schedule_background_operation(
        self,
        operation: Callable[[], Coroutine[Any, Any, object]],
    ) -> None:
        """从同步生命周期入口提交异步清理，下个状态边界会收敛异常。"""

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(operation())
            return
        task: asyncio.Task[object] = loop.create_task(operation())
        self._background_tasks.add(task)

        def collect_result(done: asyncio.Task[object]) -> None:
            self._background_tasks.discard(done)
            try:
                done.result()
            except BaseException as error:
                self._background_errors.append(error)

        task.add_done_callback(collect_result)

    async def flush_background_operations(self) -> None:
        pending = tuple(self._background_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if self._background_errors:
            raise self._background_errors.pop(0)

    def set_terminal_output(self, enabled: bool) -> None:
        """切换终端观察器，绝不重建 UsageObserver 或 SessionRecorder。"""

        identity = self._identity
        if enabled == identity._terminal_output:
            return
        if self._runtime.harness.is_running:
            raise RuntimeError("Agent 运行中，无法切换终端输出")
        if enabled:
            identity._terminal_output = True
            self._terminal_renderer = identity._create_terminal_renderer()
            self._terminal_renderer_unsubscribe = self._runtime.subscribe(
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
        """同时取消 Memory 预取、Core 流和可能在运行的压缩任务。"""

        self._execution.cancel()
        self._identity._last_stop_reason = "aborted"
        self._memory._memory_coordinator.cancel_pending()
        if self._core_compaction_task is not None:
            self._core_compaction_task.cancel()

    async def chat(self, user_message: str) -> None:
        """执行一次完整用户轮，保持 MCP/Memory/Core/JSONL 的既有时序。"""

        identity = self._identity
        memory = self._memory
        self._execution.begin()
        identity._last_stop_reason = None
        await identity._ensure_mcp_tools()
        if not identity.api_configured:
            identity._emit_notice(
                "API 未配置：设置 ANTHROPIC_API_KEY / OPENAI_API_KEY(+OPENAI_BASE_URL)，"
                "或在 TUI 中用 /model 配置。",
                role="error",
            )
            return
        await self.ensure_core_session_ready()
        if self._execution.cancelled:
            return
        await self.compact_core_context_if_needed()
        if self._execution.cancelled:
            return
        turn_start_index = len(self._runtime.messages)
        memory._prepare_turn_memory_snapshot(user_message)
        try:
            await self._runtime.prompt(user_message)
            while (
                not self._execution.cancelled
                and await self.apply_pending_core_context_reset()
            ):
                if self._execution.cancelled:
                    break
                await self._runtime.continue_()
            self.sync_core_usage()
            self.sync_core_outcome()
            self._core_compaction_required = self._context_manager.should_compact(
                self.context_runtime_state()
            )
        finally:
            try:
                if not identity.is_sub_agent:
                    await memory._update_session_memory_after_turn(
                        user_message,
                        turn_start_index,
                    )
            finally:
                memory._turn_memory_overlays = memory._build_turn_memory_overlays()

    async def run_once(self, prompt: str) -> dict[str, Any]:
        """运行一次并返回捕获的文本与本次 token 差值。"""

        self._output_buffer = []
        self._captured_assistant_text = None
        previous_input = self._usage.total_input_tokens
        previous_output = self._usage.total_output_tokens
        try:
            await self.chat(prompt)
            text = "".join(self._output_buffer)
            if not text:
                text = self._captured_assistant_text or ""
        finally:
            self._output_buffer = None
            self._captured_assistant_text = None
        return {
            "text": text,
            "tokens": {
                "input": self._usage.total_input_tokens - previous_input,
                "output": self._usage.total_output_tokens - previous_output,
            },
        }

    async def run(
        self,
        prompt: str,
        *,
        timeout: float | None = None,
    ) -> AgentRunResult:
        """执行一次并把取消、超时和 Provider 异常投影为结构化结果。"""

        usage = self._usage
        identity = self._identity
        session = self._session
        pre_input = usage.total_input_tokens
        pre_output = usage.total_output_tokens
        pre_cache = usage.total_cache_read_tokens
        pre_turns = usage.current_turns
        pre_cost = usage._get_current_cost_usd()
        start = time.monotonic()
        self._output_buffer = []
        self._captured_assistant_text = None
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
            stop_reason = identity._last_stop_reason or "completed"
            if stop_reason == "model_error":
                assistant = self.last_core_assistant()
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
            final_text = "".join(self._output_buffer or [])
            if not final_text:
                final_text = self._captured_assistant_text or ""
            self._output_buffer = None
            self._captured_assistant_text = None

        if timed_out:
            stop_reason = "timeout"
            error = error or f"timeout after {timeout}s"
        return AgentRunResult(
            session_id=session.session_state.id,
            final_text=final_text,
            stop_reason=stop_reason,
            turns=usage.current_turns - pre_turns,
            wall_time_seconds=time.monotonic() - start,
            input_tokens=usage.total_input_tokens - pre_input,
            output_tokens=usage.total_output_tokens - pre_output,
            cache_read_tokens=usage.total_cache_read_tokens - pre_cache,
            cost_usd=usage._get_current_cost_usd() - pre_cost,
            error=error,
        )

    # ─── SessionLifecycle 委托 ────────────────────────────────

    async def clear_history(self) -> None:
        await self._session_lifecycle.clear_history()

    async def restore_core_session(self, session_id: str) -> bool:
        return await self._session_lifecycle.restore_core_session(session_id)

    async def compact(self) -> None:
        await self._session_lifecycle.compact()

    async def close(self) -> None:
        await self._session_lifecycle.close()
