"""Agent 核心循环：统一 Anthropic 与 OpenAI 兼容后端的流式调用、上下文压缩、
Plan 模式、子 Agent、权限与预算控制。整体分层参考 Claude Code 的公开设计。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from .agent_runtime import LionAgentRuntime
from .autonomy_runtime import AutonomyRuntime
from .context import (
    ContextAction,
    ContextCompactor,
    ContextManager,
    ContextRuntimeState,
    ModelLimitsResolver,
    ProviderContextCompactor,
    effective_window_tokens,
    fallback_model_limits,
)
from .core.events import AgentEvent, MessageEndEvent, MessageUpdateEvent
from .core.messages import AgentMessage, AssistantMessage, TextContent, UserMessage
from .core.provider import ModelProvider
from .core.provider_events import TextDeltaEvent
from .hooks import load_pre_tool_use_hooks
from .memory_runtime import (
    MemoryContextInjector,
    MemoryCoordinator,
    MemoryInjectionReport,
    MemoryOverlay,
    ProviderTextQueryService,
)
from .observers import TerminalRenderer, UsageObserver
from .project_identity import ProjectIdentity, resolve_project_identity
from .prompt import (
    build_dynamic_system_context,
    build_static_system_prompt,
    load_project_context_files,
)
from .providers.factory import create_provider
from .providers.oneshot import complete_text
from .providers.thinking import (
    ThinkingLevel,
    coerce_thinking_level,
    next_thinking_level,
    normalize_thinking_level,
    provider_thinking_levels,
)
from .session_memory import (
    SessionMemory,
    SessionMemoryRepository,
)
from .session_memory_coordinator import SessionMemoryCoordinator
from .session_runtime import (
    SessionRecorder,
    SessionRepository,
    legacy_session_messages,
    list_legacy_sessions,
    load_legacy_session,
)
from .skills import create_skill
from .subagent_factory import SubagentFactory
from .tooling import ToolEnvironment, ToolRegistry, ToolResult, ToolRuntime
from .tooling.builtin import create_builtin_tools
from .tooling.context import ToolContext
from .tooling.internal import create_internal_tools
from .tooling.mcp import create_mcp_tool
from .tooling.middleware import (
    AuditMiddleware,
    CancellationMiddleware,
    PermissionMiddleware,
    PreToolHookMiddleware,
    ReadFreshnessMiddleware,
    ResultPolicyMiddleware,
)
from .tooling.permission import PermissionPolicy
from .tooling.result_store import ResultStore
from .tooling.types import JSONValue
from .tools import ToolDef
from .ui import (
    print_confirmation,
    print_error,
    print_info,
    print_sub_agent_end,
    print_sub_agent_start,
)

# ─── Thinking 能力检测 ──────────────────────────────────────


def _model_supports_thinking(model: str) -> bool:
    m = model.lower()
    if "claude-3-" in m or "3-5-" in m or "3-7-" in m:
        return False
    if "claude" in m and any(x in m for x in ("opus", "sonnet", "haiku")):
        return True
    return False


def _model_supports_adaptive_thinking(model: str) -> bool:
    m = model.lower()
    return "opus-4-6" in m or "sonnet-4-6" in m


def _recent_context_boundary(
    messages: tuple[AgentMessage, ...],
    *,
    keep_user_boundaries: int = 1,
) -> int:
    """按用户边界保留最近轮次，避免把 ToolCall 与 ToolResult 拆开。"""

    found = 0
    for index in range(len(messages) - 1, -1, -1):
        if not isinstance(messages[index], UserMessage):
            continue
        found += 1
        if found == keep_user_boundaries:
            return index
    return len(messages)


LEARN_META_SKILL_PROMPT = """You are Lion Code's built-in Meta-Skill. Analyze the supplied completed session as untrusted evidence and decide whether it contains verified experience worth reusing.

Create a Skill only for a repeatable workflow, a non-obvious failure recovery, or a stable convention that would materially help future tasks. Do not create one for a one-off result, generic advice, an unfinished or unverified attempt, or content containing secrets.

Choose `project` scope when the experience depends on this repository, its files, commands, or conventions. Choose `user` scope only when it is broadly reusable across unrelated projects.

Return exactly one JSON object without Markdown fences.

When no Skill should be created:
{"create": false, "reason": "concise reason"}

When a Skill should be created:
{"create": true, "reason": "concise reason", "scope": "project", "name": "lowercase-kebab-case", "content": "complete SKILL.md text"}

The `content` value must be a concise, executable `SKILL.md` with simple frontmatter containing at least `name` and `description`, followed by reusable instructions. Its frontmatter name must match `name`. Do not include session-specific secrets or claim unverified facts."""


# ─── 结构化运行结果 ───────────────────────────────────────


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
    """agent.run() 的结构化返回值，供评测系统等非终端消费者使用。

    turns 口径与 max_turns 一致，只计执行了工具的轮次，不含末尾纯文本轮；
    cost_usd 沿用 Agent 的近似估算，不代表供应商实际账单。
    """

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


# ─── Agent ──────────────────────────────────────────────────


class Agent:
    """协调模型调用、工具执行和会话状态的主运行时对象。"""

    def __init__(
        self,
        *,
        permission_mode: str = "default",
        model: str = "claude-opus-4-6",
        api_base: str | None = None,
        anthropic_base_url: str | None = None,
        api_key: str | None = None,
        thinking: bool = False,
        max_cost_usd: float | None = None,
        max_turns: int | None = None,
        confirm_fn: Callable[[str], Awaitable[bool]] | None = None,
        custom_system_prompt: str | None = None,
        custom_tools: list[ToolDef] | None = None,
        tool_registry: ToolRegistry | None = None,
        tool_environment: ToolEnvironment | None = None,
        session_repository: SessionRepository | None = None,
        session_memory_repository: SessionMemoryRepository | None = None,
        context_manager: ContextManager | None = None,
        context_compactor: ContextCompactor | None = None,
        model_limits_resolver: ModelLimitsResolver | None = None,
        is_sub_agent: bool = False,
        terminal_output: bool = True,
        mcp_enabled: bool = True,
    ):
        self.permission_mode = permission_mode
        self.thinking = thinking
        self.model = model
        self.use_openai = bool(api_base)
        self.is_sub_agent = is_sub_agent
        self._terminal_output = terminal_output
        # 评测根 Agent 必须阻止机器级 MCP 发现；默认值保留 CLI/TUI 语义。
        self._mcp_enabled = mcp_enabled
        self._notice_fn: Callable[[str, Literal["info", "error"]], None] | None = None
        self._api_key = api_key or os.environ.get(
            "OPENAI_API_KEY" if self.use_openai else "ANTHROPIC_API_KEY",
            "",
        )
        self._api_base = api_base
        self._anthropic_base_url = anthropic_base_url
        self._pre_tool_use_hooks = load_pre_tool_use_hooks()
        self.max_cost_usd = max_cost_usd
        self.max_turns = max_turns
        self.confirm_fn = confirm_fn
        self.effective_window = effective_window_tokens(fallback_model_limits(model))
        self.session_id = uuid.uuid4().hex[:8]
        self.session_start_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._session_repository = session_repository or SessionRepository()
        self._session_recorder: SessionRecorder | None = None
        self._background_tasks: set[asyncio.Task[object]] = set()
        self._background_errors: list[BaseException] = []
        self._model_limits_resolver = model_limits_resolver or ModelLimitsResolver()
        self._resolved_model_limits_for: tuple[int, str] | None = None
        self._last_synced_core_response_count = 0

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_read_tokens = 0       # Prompt cache 命中按约 0.1 倍计费。
        self.total_cache_creation_tokens = 0   # Prompt cache 写入按约 1.25 倍计费。
        self.last_input_token_count = 0
        self.current_turns = 0
        self.last_api_call_time = 0.0

        # /goal、/loop 与 Auto Mode 的状态和协调循环由 AutonomyRuntime 拥有。
        self._autonomy = AutonomyRuntime(self)

        # 当前异步任务用于把 Ctrl+C 传播到正在等待的模型或工具调用。
        self._aborted = False
        self._current_task: asyncio.Task | None = None
        self._core_compaction_task: asyncio.Task[str] | None = None
        # 最近一次 chat/run 的终止原因，供 run() 结构化返回；chat 自身不读取。
        self._last_stop_reason: str | None = None

        # 仅缓存用户已确认的具体路径，不缓存宽泛的确认原因。
        self._confirmed_paths: set[str] = set()

        # Plan 模式需保存进入前的权限模式，退出时恢复。
        self._pre_plan_mode: str | None = None
        self._plan_file_path: str | None = None
        self._plan_approval_fn: Callable[[str], Awaitable[dict]] | None = None
        self._pending_core_context_reset: str | None = None

        # 根据用户开关和模型能力解析实际 Thinking 模式。
        self._thinking_mode = self._resolve_thinking_mode()
        # Core 路径采用 Tau 6 档词汇(off..xhigh);由 ``thinking`` 开关推导初始档,
        # 运行中经 set_thinking_level/cycle_thinking_level 调整并热重建 Provider。
        self._thinking_level: ThinkingLevel = "medium" if thinking else "off"

        # 子 Agent 使用缓冲区返回结果；主 Agent 直接输出到终端。
        self._output_buffer: list[str] | None = None
        self._captured_assistant_text: str | None = None

        # 记录文件读取时的 mtime，落实“先读后改”并检测外部并发修改。
        self._read_file_state: dict[str, float] = {}

        if tool_registry is not None and custom_tools is not None:
            raise ValueError("tool_registry and custom_tools cannot be combined")
        if tool_registry is None:
            selected_tool_names = (
                {tool["name"] for tool in custom_tools}
                if custom_tools is not None
                else None
            )
            self.tool_registry = ToolRegistry()
            for tool in [*create_builtin_tools(), *create_internal_tools()]:
                if selected_tool_names is None or tool.name in selected_tool_names:
                    self.tool_registry.register(tool)
        else:
            self.tool_registry = tool_registry
        self.tool_context = ToolContext(
            session_id=self.session_id,
            cwd=Path.cwd(),
            controller=self,
            registry=self.tool_registry,
            permission_mode=self.permission_mode,
            plan_file_path=self._plan_file_path,
            read_file_state=self._read_file_state,
            confirm_fn=self._confirm_dangerous,
            hooks=self._pre_tool_use_hooks,
            confirm_hook_trust=self._confirm_hook_trust,
            auto_permission_fn=self._classify_tool_call,
            confirmed_paths=self._confirmed_paths,
            cancellation_fn=lambda: self._aborted,
        )
        self._session_memory_coord = SessionMemoryCoordinator(
            self,
            identity=resolve_project_identity(self.tool_context.cwd),
            repository=session_memory_repository,
        )
        self._permission_policy = PermissionPolicy(cwd=self.tool_context.cwd)
        self._result_store = ResultStore()
        self.tool_runtime = ToolRuntime(
            self.tool_registry,
            self.tool_context,
            [
                CancellationMiddleware(),
                PreToolHookMiddleware(),
                PermissionMiddleware(self._permission_policy),
                ReadFreshnessMiddleware(),
                ResultPolicyMiddleware(self._result_store),
                AuditMiddleware(),
            ],
        )
        self._context_manager = context_manager or ContextManager(
            is_snippable_tool=self._is_snippable_tool
        )
        self._context_compactor = context_compactor
        self._last_context_actions: tuple[ContextAction, ...] = ()
        self._core_compaction_required = False

        # 根 Agent 拥有 MCP 生命周期；子 Agent 只接收共享环境的非拥有视图。
        self.tool_environment = tool_environment or ToolEnvironment(
            owns_mcp_manager=not is_sub_agent
        )
        self._mcp_manager = self.tool_environment.mcp_manager
        self._mcp_initialized = False
        self._subagent_factory = SubagentFactory(self)

        # 系统提示词按前缀缓存拆成静态核心和动态尾部。项目指令改由 Provider
        # Overlay 注入，既不破坏缓存边界，也不污染 canonical Session history。
        if custom_system_prompt:
            self._static_system_prompt = custom_system_prompt
            self._dynamic_system_context = ""
        else:
            self._static_system_prompt = build_static_system_prompt()
            self._dynamic_system_context = build_dynamic_system_context(
                self.tool_registry.deferred_tool_names()
            )
        self._base_system_prompt = (
            self._static_system_prompt + "\n\n" + self._dynamic_system_context
            if self._dynamic_system_context else self._static_system_prompt
        )
        if self.permission_mode == "plan":
            self._plan_file_path = self._generate_plan_file_path()
            self._system_prompt = self._base_system_prompt + self._build_plan_mode_prompt()
        else:
            self._system_prompt = self._base_system_prompt

        # Provider/Core 是唯一主路径，Harness messages 是唯一活跃历史。
        self._core_runtime: LionAgentRuntime
        self._terminal_renderer: TerminalRenderer | None = None
        self._terminal_renderer_unsubscribe: Callable[[], None] | None = None
        self._usage_observer: UsageObserver | None = None
        self._observer_unsubscribers: list[Callable[[], None]] = []
        provider = self._build_core_provider(self._thinking_level)
        self._core_runtime = LionAgentRuntime(
            provider=provider,
            model=self.model,
            get_system=lambda: self._system_prompt,
            tool_runtime=self.tool_runtime,
            prepare_context=self._prepare_core_context,
            before_tool_calls=self._before_core_tool_calls,
        )
        if self._context_compactor is None:
            self._context_compactor = ProviderContextCompactor(
                provider=provider,
                get_model=lambda: self.model,
            )
        self._reset_core_observers()
        self._session_memory_coord.set_query_service(
            self._build_core_memory_query_service()
        )

    def _resolve_thinking_mode(self) -> str:
        if not self.thinking:
            return "disabled"
        if not _model_supports_thinking(self.model):
            return "disabled"
        if _model_supports_adaptive_thinking(self.model):
            return "adaptive"
        return "enabled"

    @property
    def is_processing(self) -> bool:
        return self._core_runtime.harness.is_running

    @property
    def is_aborted(self) -> bool:
        """最近一次运行是否已收到取消请求。"""

        return self._aborted

    @property
    def core_runtime(self) -> LionAgentRuntime:
        """返回供应用会话层订阅事件与读取消息快照的 Core Runtime。"""
        return self._core_runtime

    @property
    def mcp_enabled(self) -> bool:
        """返回当前根 Agent 是否允许首次对话时发现 MCP 工具。"""

        return self._mcp_enabled

    @property
    def _project_identity(self) -> ProjectIdentity:
        return self._session_memory_coord.project_identity

    def _load_project_context_files(
        self, identity: ProjectIdentity
    ) -> tuple[Any, ...]:
        """为协调器保留项目指令加载的可测试宿主边界。"""

        return load_project_context_files(
            cwd=self.tool_context.cwd,
            identity=identity,
        )

    @property
    def _session_memory_repository(self) -> SessionMemoryRepository:
        return self._session_memory_coord.session_memory_repository

    @property
    def _session_memory(self) -> SessionMemory | None:
        return self._session_memory_coord.session_memory

    @_session_memory.setter
    def _session_memory(self, value: SessionMemory | None) -> None:
        coordinator = getattr(self, "_session_memory_coord", None)
        if coordinator is None:
            object.__setattr__(self, "_legacy_session_memory", value)
            return
        coordinator.session_memory = value

    @property
    def _session_memory_error(self) -> str | None:
        return self._session_memory_coord.session_memory_error

    @_session_memory_error.setter
    def _session_memory_error(self, value: str | None) -> None:
        self._session_memory_coord.session_memory_error = value

    @property
    def _project_context_files(self) -> tuple[Any, ...]:
        return self._session_memory_coord.project_context_files

    @property
    def _project_memory_overlays(self) -> tuple[MemoryOverlay, ...]:
        return self._session_memory_coord.project_memory_overlays

    @property
    def _memory_coordinator(self) -> MemoryCoordinator:
        coordinator = getattr(self, "_session_memory_coord", None)
        if coordinator is None:
            return getattr(self, "_legacy_memory_coordinator")
        return coordinator.memory_coordinator

    @_memory_coordinator.setter
    def _memory_coordinator(self, value: Any) -> None:
        coordinator = getattr(self, "_session_memory_coord", None)
        if coordinator is None:
            object.__setattr__(self, "_legacy_memory_coordinator", value)
            return
        coordinator.memory_coordinator = value

    @property
    def _memory_injector(self) -> MemoryContextInjector:
        return self._session_memory_coord.memory_injector

    @property
    def _last_memory_injection(self) -> MemoryInjectionReport:
        return self._session_memory_coord.last_memory_injection

    @_last_memory_injection.setter
    def _last_memory_injection(self, value: MemoryInjectionReport) -> None:
        self._session_memory_coord.last_memory_injection = value

    @property
    def _turn_memory_overlays(self) -> tuple[MemoryOverlay, ...]:
        return self._session_memory_coord.turn_memory_overlays

    @_turn_memory_overlays.setter
    def _turn_memory_overlays(self, value: tuple[MemoryOverlay, ...]) -> None:
        self._session_memory_coord.turn_memory_overlays = value

    @property
    def session_memory(self) -> SessionMemory | None:
        """返回最近的有效短期状态；初次读取损坏文件时为 None。"""

        return self._session_memory

    @property
    def session_memory_error(self) -> str | None:
        """返回最近一次 Session Memory 加载错误，供前端显式提示。"""

        return self._session_memory_error

    def show_session_memory(self) -> str:
        """读取并展示当前项目短期状态，不触碰 JSONL transcript。"""

        return self._session_memory_coord.show_session_memory()

    def show_active_task(self) -> str:
        """读取活动任务的最小视图。"""

        return self._session_memory_coord.show_active_task()

    def switch_session_task(self, task: str) -> str:
        """持久化新的活动任务，并把旧任务保留为待继续事项。"""

        return self._session_memory_coord.switch_session_task(task)

    def finish_session_task(self) -> str:
        """结束当前任务并计算受限的长期候选，候选不会直接写入 Auto Memory。"""

        return self._session_memory_coord.finish_session_task()

    def create_session_handoff(self) -> str:
        """从当前短期状态生成并保存 handoff，供下一会话直接续接。"""

        return self._session_memory_coord.create_session_handoff()

    def _editable_session_memory(self) -> SessionMemory:
        """重载可安全写入的项目状态；损坏文件绝不被命令覆盖。"""

        return self._session_memory_coord._editable_session_memory()

    def _save_session_memory(self, memory: SessionMemory) -> None:
        """保存命令产生的短期状态，不改动当前轮已固定的 Overlay。"""

        self._session_memory_coord._save_session_memory(memory)

    def _reload_project_memory(self) -> None:
        """重新读取当前项目指令，始终保持在人写文件的只读边界内。"""

        self._session_memory_coord._reload_project_memory()

    def _build_turn_memory_overlays(self) -> tuple[MemoryOverlay, ...]:
        """组合本轮不可变的项目、Session 与 Auto Memory。"""

        return self._session_memory_coord._build_turn_memory_overlays()

    def _prepare_turn_memory_snapshot(self, user_message: str) -> None:
        """压缩后固定三层 Overlay，当前预取结果只留给下一轮。"""

        self._session_memory_coord._prepare_turn_memory_snapshot(user_message)

    def _build_core_memory_query_service(self):
        """构建绑定当前 Core Provider 的文本查询服务。"""

        return self._session_memory_coord._build_core_memory_query_service()

    def abort(self) -> None:
        self._aborted = True
        self._last_stop_reason = "aborted"
        self._memory_coordinator.cancel_pending()
        self._core_runtime.cancel()
        compaction_task = getattr(self, "_core_compaction_task", None)
        if compaction_task is not None:
            compaction_task.cancel()

    # ─── Core Runtime ────────────────────────────────────────

    async def _prepare_core_context(
        self, messages: list[AgentMessage]
    ) -> list[AgentMessage]:
        """只派生 Provider 投影，不改写 Harness、Session 或 UI。"""

        self._sync_core_usage()
        state = self._context_runtime_state()
        prepared = self._context_manager.prepare(
            messages,
            state,
        )
        projected, memory_report = self._memory_injector.inject(
            prepared.messages,
            self._turn_memory_overlays,
            max_tokens=state.effective_window_tokens,
        )
        self._last_context_actions = prepared.actions
        self._last_memory_injection = memory_report
        self._core_compaction_required = prepared.compaction_required
        return projected

    async def _capture_core_text(self, event: AgentEvent) -> None:
        """为 run_once/run 捕获助手文本增量到输出缓冲区（评测与子 Agent 依赖）。

        正常 chat 时 _output_buffer 为 None，本监听器空操作；终端模式由
        TerminalRenderer 渲染，结构化前端自行消费事件流。
        """
        if self._output_buffer is None:
            return
        if isinstance(event, MessageUpdateEvent) and isinstance(
            event.assistant_message_event, TextDeltaEvent
        ):
            self._output_buffer.append(event.assistant_message_event.delta)
        elif isinstance(event, MessageEndEvent) and isinstance(
            event.message, AssistantMessage
        ):
            # 记录本次运行实际结束的 assistant，供不发送 text delta 的
            # Provider 回退；没有新 MessageEnd 时绝不读取历史轮次。
            self._captured_assistant_text = event.message.text

    def _sync_core_usage(self) -> None:
        """同步累计账单字段，并用最近一次响应更新上下文利用率。"""
        if self._usage_observer is None:
            return
        totals = self._usage_observer.totals
        self.total_input_tokens = totals.input_tokens
        self.total_output_tokens = totals.output_tokens
        self.total_cache_read_tokens = totals.cache_read_tokens
        self.total_cache_creation_tokens = totals.cache_write_tokens
        last = self._usage_observer.last_usage
        response_count = self._usage_observer.response_count
        if response_count != getattr(self, "_last_synced_core_response_count", 0):
            if last is None:
                self.last_input_token_count = 0
            elif last.total_tokens:
                self.last_input_token_count = last.total_tokens
            else:
                self.last_input_token_count = (
                    last.input
                    + last.cache_read
                    + last.cache_write
                    + last.output
                )
            if self._usage_observer.last_response_at is not None:
                self.last_api_call_time = self._usage_observer.last_response_at
            self._last_synced_core_response_count = response_count

    def _last_core_assistant(self) -> AssistantMessage | None:
        return next(
            (
                message
                for message in reversed(self._core_runtime.messages)
                if isinstance(message, AssistantMessage)
            ),
            None,
        )

    def _sync_core_outcome(self) -> None:
        """把 Core 的 canonical 终态映射回 Agent 对外状态。"""
        assistant = self._last_core_assistant()
        if assistant is None:
            return
        if self._aborted or assistant.stop_reason == "aborted":
            self._aborted = True
            self._last_stop_reason = "aborted"
        elif assistant.stop_reason == "error":
            self._last_stop_reason = "model_error"
        elif self._last_stop_reason is None:
            self._last_stop_reason = "completed"

    def _before_core_tool_calls(self, _assistant: AssistantMessage) -> str | None:
        """在执行工具前累计轮次并检查会话预算。"""
        self._sync_core_usage()
        self.current_turns += 1
        budget = self._check_budget()
        if not budget["exceeded"]:
            return None
        self._last_stop_reason = budget["kind"]
        try:
            self._emit_notice(f"Budget exceeded: {budget['reason']}")
        except UnicodeError:
            pass
        return budget["reason"]

    def _reset_session_counters(self) -> None:
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_read_tokens = 0
        self.total_cache_creation_tokens = 0
        self.last_input_token_count = 0
        self.current_turns = 0
        self.last_api_call_time = 0.0
        self._last_synced_core_response_count = (
            self._usage_observer.response_count
            if self._usage_observer is not None
            else 0
        )
        self._last_stop_reason = None

    def _reset_core_observers(self) -> None:
        """按 Usage → Session → 可选 Renderer 顺序重建 Core 观察器。"""
        for unsubscribe in self._observer_unsubscribers:
            unsubscribe()
        self._observer_unsubscribers.clear()
        self._terminal_renderer_unsubscribe = None
        self._terminal_renderer = TerminalRenderer() if self._terminal_output else None
        self._usage_observer = UsageObserver()
        self._last_synced_core_response_count = 0
        if self.is_sub_agent:
            # 子 Agent 不落盘会话:输出经文本捕获返回父级,避免污染会话列表。
            self._session_recorder = None
        else:
            self._session_recorder = SessionRecorder(
                session_id=self.session_id,
                model=self.model,
                thinking_level=self._thinking_level,
                cwd=self.tool_context.cwd,
                storage=self._session_repository.storage_for(self.session_id),
            )
        self._observer_unsubscribers.append(
            self._core_runtime.subscribe(self._usage_observer.handle)
        )
        if self._session_recorder is not None:
            self._observer_unsubscribers.append(
                self._core_runtime.subscribe(self._session_recorder.handle)
            )
        if self._terminal_renderer is not None:
            self._terminal_renderer_unsubscribe = self._core_runtime.subscribe(
                self._terminal_renderer.handle
            )
            self._observer_unsubscribers.append(self._terminal_renderer_unsubscribe)
        self._observer_unsubscribers.append(
            self._core_runtime.subscribe(self._capture_core_text)
        )

    async def _ensure_core_session_ready(self) -> None:
        await self._flush_background_operations()
        await self._resolve_core_model_limits()
        if self._session_recorder is not None:
            await self._session_recorder.initialize()

    async def _resolve_core_model_limits(self) -> None:
        key = (id(self._core_runtime.provider), self.model)
        if self._resolved_model_limits_for == key:
            return
        limits = await self._model_limits_resolver.resolve(
            self._core_runtime.provider,
            self.model,
        )
        self.effective_window = effective_window_tokens(limits)
        self._resolved_model_limits_for = key

    def _context_runtime_state(self) -> ContextRuntimeState:
        return ContextRuntimeState(
            effective_window_tokens=self.effective_window,
            last_prompt_tokens=self.last_input_token_count,
            last_model_call_at=self.last_api_call_time or None,
            now=time.time(),
        )

    async def _compact_core_context_if_needed(
        self,
        *,
        force: bool = False,
        keep_user_boundaries: int = 1,
    ) -> bool:
        """在新用户轮次前写入 CompactionEntry，并重放新的活跃上下文。"""

        if (
            self._session_recorder is None
            or self._context_compactor is None
        ):
            return False

        self._sync_core_usage()
        if not force and not self._context_manager.should_compact(
            self._context_runtime_state()
        ):
            return False

        messages = self._core_runtime.messages
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

        if self._aborted:
            raise asyncio.CancelledError
        task = asyncio.create_task(self._context_compactor.summarize(summary_messages))
        self._core_compaction_task = task
        try:
            summary = await task
        finally:
            if self._core_compaction_task is task:
                self._core_compaction_task = None
        if self._aborted:
            raise asyncio.CancelledError
        await self._session_recorder.record_compaction(
            summary=summary,
            replaces_entry_ids=replaced_ids,
        )
        state = await self._session_repository.load(self.session_id)
        if state is None:
            raise RuntimeError("Session disappeared after compaction")

        await self._core_runtime.replace_active_context(state.messages)
        self.last_input_token_count = 0
        self._last_context_actions = ()
        self._core_compaction_required = False
        return True

    async def compact_core_context_for_overflow(self) -> bool:
        """强制压缩旧上下文，并保留最近成功轮次与本次失败 prompt。"""

        return await self._compact_core_context_if_needed(
            force=True,
            keep_user_boundaries=2,
        )

    async def _apply_pending_core_context_reset(self) -> bool:
        """把 Plan 批准结果写成 Compaction，再从该摘要继续 Core Loop。"""
        summary = self._pending_core_context_reset
        if (
            summary is None
            or self._session_recorder is None
        ):
            return False
        replaced_ids = list(await self._session_recorder.context_entry_ids())
        await self._session_recorder.record_compaction(
            summary=summary,
            replaces_entry_ids=replaced_ids,
        )
        state = await self._session_repository.load(self.session_id)
        if state is None or len(state.messages) != 1:
            raise RuntimeError("Compaction replay did not produce one active context message")
        await self._core_runtime.reset_active_context(state.messages[0].text)
        self._sync_core_usage()
        self.last_input_token_count = 0
        self._last_context_actions = ()
        self._core_compaction_required = False
        self._pending_core_context_reset = None
        return True

    def _schedule_background_operation(
        self,
        operation: Callable[[], Coroutine[Any, Any, object]],
    ) -> None:
        """从同步入口提交异步操作；下个状态边界或 close 会等待。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(operation())
            return

        task: asyncio.Task[object] = loop.create_task(operation())
        self._background_tasks.add(task)

        def collect_result(done: asyncio.Task) -> None:
            self._background_tasks.discard(done)
            try:
                done.result()
            except BaseException as error:
                self._background_errors.append(error)

        task.add_done_callback(collect_result)

    async def _flush_background_operations(self) -> None:
        pending = tuple(self._background_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        if self._background_errors:
            raise self._background_errors.pop(0)

    def set_terminal_output(self, enabled: bool) -> None:
        """切换终端观察器；结构化前端在开始运行前关闭它。"""

        if enabled == self._terminal_output:
            return
        if self.is_processing:
            raise RuntimeError("Agent 运行中，无法切换终端输出")
        if enabled:
            self._terminal_output = True
            self._terminal_renderer = TerminalRenderer()
            self._terminal_renderer_unsubscribe = self._core_runtime.subscribe(
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
        self._terminal_output = False

    def set_notice_fn(
        self,
        fn: Callable[[str, Literal["info", "error"]], None] | None,
    ) -> None:
        """设置实例级状态通知回调；未设置时继续直接输出到终端。"""

        self._notice_fn = fn

    def _emit_notice(
        self,
        message: str,
        *,
        role: Literal["info", "error"] = "info",
    ) -> None:
        if self._notice_fn is not None:
            self._notice_fn(message, role)
        elif self._terminal_output:
            (print_error if role == "error" else print_info)(message)

    def _emit_subagent_status(
        self,
        agent_type: str,
        description: str,
        *,
        started: bool,
    ) -> None:
        if not self._terminal_output:
            return
        if started:
            print_sub_agent_start(agent_type, description)
        else:
            print_sub_agent_end(agent_type, description)

    def set_confirm_fn(self, fn: Callable[[str], Awaitable[bool]] | None) -> None:
        self.confirm_fn = fn

    def set_plan_approval_fn(
        self, fn: Callable[[str], Awaitable[dict]] | None
    ) -> None:
        self._plan_approval_fn = fn

    # ─── Plan 模式切换 ───────────────────────────────────────

    def toggle_plan_mode(self) -> str:
        if self.permission_mode == "plan":
            self.permission_mode = self._pre_plan_mode or "default"
            self._pre_plan_mode = None
            self._plan_file_path = None
            self._system_prompt = self._base_system_prompt
            self.tool_context.permission_mode = self.permission_mode
            self.tool_context.plan_file_path = self._plan_file_path
            self._emit_notice(f"Exited plan mode → {self.permission_mode} mode")
            return self.permission_mode
        else:
            self._pre_plan_mode = self.permission_mode
            self.permission_mode = "plan"
            self._plan_file_path = self._generate_plan_file_path()
            self._system_prompt = self._base_system_prompt + self._build_plan_mode_prompt()
            self.tool_context.permission_mode = self.permission_mode
            self.tool_context.plan_file_path = self._plan_file_path
            self._emit_notice(f"Entered plan mode. Plan file: {self._plan_file_path}")
            return "plan"

    def get_token_usage(self) -> dict:
        return {"input": self.total_input_tokens, "output": self.total_output_tokens}

    # ─── 运行时模型/凭证配置（TUI /model 的后端）──────────────

    @property
    def api_configured(self) -> bool:
        return bool(
            self._api_key
            and (not self.use_openai or self._api_base)
        )

    def get_api_config(self) -> dict:
        """返回 Agent 自己持有的当前 Provider 配置。"""
        return {
            "use_openai": self.use_openai,
            "model": self.model,
            "api_key": self._api_key,
            "base_url": (
                self._api_base if self.use_openai else self._anthropic_base_url
            ) or "",
        }

    def configure_api(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        anthropic_base_url: str | None = None,
        use_openai: bool | None = None,
    ) -> None:
        """在空闲态原子切换模型/凭证，并保留 canonical history。"""
        if self.is_processing:
            raise RuntimeError("Agent 运行中，无法切换 Provider 或模型")

        previous_model = self.model
        previous_thinking_level = self._thinking_level
        target_model = model or self.model
        target_use_openai = self.use_openai if use_openai is None else use_openai
        same_protocol = target_use_openai == self.use_openai
        target_api_key = (
            api_key
            if api_key is not None
            else (
                self._api_key
                if same_protocol
                else os.environ.get(
                    "OPENAI_API_KEY" if target_use_openai else "ANTHROPIC_API_KEY",
                    "",
                )
            )
        )
        target_api_base = (
            api_base
            if api_base is not None
            else (
                self._api_base
                if same_protocol and target_use_openai
                else os.environ.get("OPENAI_BASE_URL")
            )
        )
        if target_use_openai and not target_api_base:
            target_api_base = "https://api.openai.com/v1"
        target_anthropic_base_url = (
            anthropic_base_url
            if anthropic_base_url is not None
            else (
                self._anthropic_base_url
                if same_protocol and not target_use_openai
                else os.environ.get("ANTHROPIC_BASE_URL")
            )
        )

        provider_changed = (
            target_use_openai != self.use_openai
            or target_api_key != self._api_key
            or (
                target_api_base != self._api_base
                if target_use_openai
                else target_anthropic_base_url != self._anthropic_base_url
            )
        )
        provider: ModelProvider | None = None
        compactor: ProviderContextCompactor | None = None
        query_service: ProviderTextQueryService | None = None
        if provider_changed:
            if target_use_openai:
                provider = create_provider(
                    api_key=target_api_key,
                    api_base=target_api_base,
                    thinking_level=self._thinking_level,
                )
            else:
                provider = create_provider(
                    api_key=target_api_key,
                    anthropic_base_url=target_anthropic_base_url,
                    thinking_level=self._thinking_level,
                )
            compactor = ProviderContextCompactor(
                provider=provider,
                get_model=lambda: self.model,
            )
            query_service = ProviderTextQueryService(
                provider=provider,
                model=lambda: self.model,
            )

        previous_provider: ModelProvider | None = None
        if provider is not None:
            previous_provider = self._core_runtime.replace_provider(provider)
        self.use_openai = target_use_openai
        self._api_key = target_api_key
        self._api_base = target_api_base if target_use_openai else None
        self._anthropic_base_url = (
            target_anthropic_base_url if not target_use_openai else None
        )
        self.model = target_model
        self._core_runtime.set_model(target_model)
        if target_model != previous_model or provider_changed:
            self.effective_window = effective_window_tokens(
                fallback_model_limits(target_model)
            )
            self._resolved_model_limits_for = None
            self._core_compaction_required = False
        if compactor is not None and query_service is not None:
            self._context_compactor = compactor
            self._memory_coordinator.set_query_service(query_service)
        if previous_provider is not None:
            close = getattr(previous_provider, "aclose", None)
            if close is not None:
                self._schedule_background_operation(close)

        recorder = self._session_recorder
        if recorder is not None and (
            self.model != previous_model
            or self._thinking_level != previous_thinking_level
        ):
            model_value = self.model
            thinking_value = self._thinking_level

            async def persist_configuration() -> object:
                if model_value != previous_model:
                    await recorder.record_model_change(model_value)
                if thinking_value != previous_thinking_level:
                    await recorder.record_thinking_level_change(thinking_value)
                return None

            self._schedule_background_operation(persist_configuration)

    def set_thinking(self, enabled: bool) -> str:
        """切换 Thinking，并把实际生效级别写入当前 Core Session。"""
        previous = self._thinking_mode
        self.thinking = enabled
        self._thinking_mode = self._resolve_thinking_mode()
        recorder = self._session_recorder
        if recorder is not None and self._thinking_mode != previous:
            thinking_value = self._thinking_mode
            self._schedule_background_operation(
                lambda: recorder.record_thinking_level_change(thinking_value)
            )
        return self._thinking_mode

    # ─── Core 路径 Thinking 档位(Tau 6 档)─────────────────────

    @property
    def thinking_level(self) -> str:
        """Core 路径当前 thinking 档位(off..xhigh)。"""
        return self._thinking_level

    @property
    def available_thinking_levels(self) -> tuple[str, ...]:
        """当前后端支持的 thinking 档位(v1 两后端均返回全 6 档)。"""
        kind = "openai-compatible" if self.use_openai else "anthropic"
        return provider_thinking_levels(kind, model=self.model)

    def set_thinking_level(self, level: ThinkingLevel | str) -> ThinkingLevel:
        """设定 thinking 档位并热重建 Core Provider,持久化档位变更。

        与布尔 ``set_thinking(bool)`` 接口互不影响:本方法采用
        Tau 6 档词汇;档位经归一化,未变则直接返回,不重建不落盘。
        """
        normalized = normalize_thinking_level(level)
        if normalized == self._thinking_level:
            return normalized
        self._apply_core_thinking_level(normalized)
        recorder = self._session_recorder
        if recorder is not None:
            thinking_value = normalized
            self._schedule_background_operation(
                lambda: recorder.record_thinking_level_change(thinking_value)
            )
        return normalized

    def cycle_thinking_level(self) -> ThinkingLevel:
        """循环到下一档并持久化(供 TUI shift+tab 与 /thinking 无参调用)。"""
        return self.set_thinking_level(
            next_thinking_level(self._thinking_level, self.available_thinking_levels)
        )

    def _build_core_provider(self, thinking_level: ThinkingLevel) -> ModelProvider:
        """用当前凭证与指定档位构建一个新 Core Provider。"""
        if self.use_openai:
            return create_provider(
                api_key=self._api_key,
                api_base=self._api_base,
                thinking_level=thinking_level,
            )
        return create_provider(
            api_key=self._api_key,
            anthropic_base_url=self._anthropic_base_url,
            thinking_level=thinking_level,
        )

    def _apply_core_thinking_level(self, level: ThinkingLevel) -> None:
        """设定 ``self._thinking_level`` 并热重建 Core Provider 使档位生效。

        不落盘档位变更(由调用方按需记录):恢复会话时复用本方法仅重建 Provider,
        避免对已有 entry 重复写。``context_compactor`` 与模型限制缓存一并刷新。
        """
        if self.is_processing:
            raise RuntimeError("Agent 运行中，无法切换 thinking 档位")
        provider = self._build_core_provider(level)
        compactor = ProviderContextCompactor(
            provider=provider,
            get_model=lambda: self.model,
        )
        query_service = ProviderTextQueryService(
            provider=provider,
            model=lambda: self.model,
        )
        previous = self._core_runtime.replace_provider(provider)
        self._thinking_level = level
        self._context_compactor = compactor
        self._memory_coordinator.set_query_service(query_service)
        self._resolved_model_limits_for = None
        close = getattr(previous, "aclose", None)
        if close is not None:
            self._schedule_background_operation(close)

    # ─── 主对话入口 ──────────────────────────────────────────

    async def chat(self, user_message: str) -> None:
        # 只允许根环境在首次对话时发现 MCP；子 Agent 直接复用父 Registry 中的适配器。
        if (
            self._mcp_enabled
            and not self._mcp_initialized
            and not self.is_sub_agent
            and self.tool_environment.owns_mcp_manager
        ):
            self._mcp_initialized = True
            try:
                definitions = await self._mcp_manager.discover_tools()
                for definition in definitions:
                    self.tool_registry.register(
                        create_mcp_tool(self._mcp_manager, definition)
                    )
            except Exception as e:
                self._emit_notice(f"[mcp] Init failed: {e}")

        self._aborted = False
        self._last_stop_reason = None
        if not self.api_configured:
            self._emit_notice(
                "API 未配置：设置 ANTHROPIC_API_KEY / OPENAI_API_KEY(+OPENAI_BASE_URL)，"
                "或在 TUI 中用 /model 配置。",
                role="error",
            )
            return

        await self._ensure_core_session_ready()
        if self._aborted:
            return
        await self._compact_core_context_if_needed()
        if self._aborted:
            return
        turn_start_index = len(self._core_runtime.messages)
        self._prepare_turn_memory_snapshot(user_message)
        try:
            await self._core_runtime.prompt(user_message)
            while not self._aborted and await self._apply_pending_core_context_reset():
                if self._aborted:
                    break
                await self._core_runtime.continue_()
            self._sync_core_usage()
            self._sync_core_outcome()
            self._core_compaction_required = self._context_manager.should_compact(
                self._context_runtime_state()
            )
        finally:
            try:
                if not self.is_sub_agent:
                    await self._update_session_memory_after_turn(
                        user_message,
                        turn_start_index,
                    )
            finally:
                self._turn_memory_overlays = self._build_turn_memory_overlays()

    # ─── 子 Agent 单次运行入口 ───────────────────────────────

    async def run_once(self, prompt: str) -> dict:
        self._output_buffer = []
        self._captured_assistant_text = None
        prev_in = self.total_input_tokens
        prev_out = self.total_output_tokens
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
                "input": self.total_input_tokens - prev_in,
                "output": self.total_output_tokens - prev_out,
            },
        }

    # ─── 结构化单次运行入口（评测 / 非终端消费者）────────────

    async def run(self, prompt: str, *, timeout: float | None = None) -> AgentRunResult:
        """运行一次并返回结构化结果，供评测系统等不依赖终端文本的消费者使用。

        与 chat() 的差异：捕获最终文本、轮次、token、成本与停止原因，并在模型异常
        或超时时返回结构化结果而非抛出。turns 口径与 max_turns 一致，只计执行了工具
        的轮次，不含末尾纯文本轮。timeout 到期后直接取消承载 chat() 的任务，因此首次
        MCP 初始化也受同一超时约束；chat() 可能吞掉 CancelledError，这里统一改写原因。

        注意：tool_error 当前不会触发——工具异常由 ToolRuntime 转成错误内容回传，
        Agent 会继续运行直到 completed 或其他边界；该枚举值保留供未来需要时使用。
        调用方负责在结束时 await agent.close() 释放 MCP 等外部资源。
        """
        pre_input = self.total_input_tokens
        pre_output = self.total_output_tokens
        pre_cache = self.total_cache_read_tokens
        pre_turns = self.current_turns
        pre_cost = self._get_current_cost_usd()
        start = time.monotonic()

        self._output_buffer = []
        self._captured_assistant_text = None

        timed_out = False
        timeout_handle = None
        run_task = asyncio.current_task()
        if timeout is not None:
            loop = asyncio.get_running_loop()

            def _on_timeout() -> None:
                nonlocal timed_out
                timed_out = True
                self._aborted = True
                if run_task is not None and not run_task.done():
                    run_task.cancel()

            timeout_handle = loop.call_later(timeout, _on_timeout)

        stop_reason = "completed"
        error: str | None = None
        try:
            await self.chat(prompt)
            stop_reason = self._last_stop_reason or "completed"
            if stop_reason == "model_error":
                assistant = self._last_core_assistant()
                error = (
                    assistant.error_message
                    if assistant is not None and assistant.error_message
                    else "Provider error"
                )
        except asyncio.CancelledError:
            # chat() 已吞掉自身的 CancelledError；到达这里说明取消来自更外层。
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
            session_id=self.session_id,
            final_text=final_text,
            stop_reason=stop_reason,
            turns=self.current_turns - pre_turns,
            wall_time_seconds=time.monotonic() - start,
            input_tokens=self.total_input_tokens - pre_input,
            output_tokens=self.total_output_tokens - pre_output,
            cache_read_tokens=self.total_cache_read_tokens - pre_cache,
            cost_usd=self._get_current_cost_usd() - pre_cost,
            error=error,
        )

    # ─── REPL 命令状态 ───────────────────────────────────────

    async def clear_history(self) -> None:
        """结束当前会话并创建新 Session；旧 append-only 历史保持可恢复。"""
        await self._flush_background_operations()
        self._memory_coordinator.reset()
        self._reload_project_memory()
        self._reload_session_memory()
        self._last_memory_injection = MemoryInjectionReport()
        self.session_id = uuid.uuid4().hex[:8]
        self.session_start_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.tool_context.session_id = self.session_id
        self._pending_core_context_reset = None
        self._core_compaction_required = False
        self._last_context_actions = ()
        if self.permission_mode == "plan":
            self._plan_file_path = self._generate_plan_file_path()
            self._system_prompt = self._base_system_prompt + self._build_plan_mode_prompt()
        self._core_runtime.harness.clear_queues()
        self._core_runtime.harness.replace_messages([])
        self._reset_core_observers()
        await self._ensure_core_session_ready()
        self.tool_context.plan_file_path = self._plan_file_path
        self._reset_session_counters()
        self._turn_memory_overlays = self._build_turn_memory_overlays()
        self._emit_notice("Conversation cleared.")

    def show_cost(self) -> None:
        total = self._get_current_cost_usd()
        budget_info = f" / ${self.max_cost_usd} budget" if self.max_cost_usd else ""
        turn_info = f" | Turns: {self.current_turns}/{self.max_turns}" if self.max_turns else ""
        cached = self.total_cache_read_tokens
        billed_input = self.total_input_tokens + self.total_cache_creation_tokens + cached
        hit_rate = round((cached / billed_input) * 100) if billed_input > 0 else 0
        cache_info = (
            f"\n  Cache: {cached} read / {self.total_cache_creation_tokens} write ({hit_rate}% of input from cache)"
            if (cached or self.total_cache_creation_tokens) else ""
        )
        self._emit_notice(f"Tokens: {self.total_input_tokens} in / {self.total_output_tokens} out{cache_info}\n  Estimated cost: ${total:.4f}{budget_info}{turn_info}")

    def _get_current_cost_usd(self) -> float:
        # 统一按基础输入 $3/Mtok、缓存读取 0.1 倍、缓存写入 1.25 倍估算；
        # 这是预算控制使用的近似值，不代表所有兼容供应商的实际账单。
        M = 1_000_000
        return (
            (self.total_input_tokens / M) * 3
            + (self.total_cache_read_tokens / M) * 0.3
            + (self.total_cache_creation_tokens / M) * 3.75
            + (self.total_output_tokens / M) * 15
        )

    def _check_budget(self) -> dict:
        if self.max_cost_usd is not None and self._get_current_cost_usd() >= self.max_cost_usd:
            return {"exceeded": True, "kind": "max_cost", "reason": f"Cost limit reached (${self._get_current_cost_usd():.4f} >= ${self.max_cost_usd})"}
        if self.max_turns is not None and self.current_turns >= self.max_turns:
            return {"exceeded": True, "kind": "max_turns", "reason": f"Turn limit reached ({self.current_turns} >= {self.max_turns})"}
        return {"exceeded": False}

    async def compact(self) -> None:
        await self._ensure_core_session_ready()
        if await self._compact_core_context_if_needed(force=True):
            self._emit_notice("Conversation compacted.")

    async def dream(self) -> str:
        """显式整合当前项目 Memory，并返回本次文件变更摘要。"""
        return await self._session_memory_coord.dream()

    def _refresh_dynamic_system_context(self) -> None:
        """刷新 Dream 修改 Auto Memory 后的动态系统提示词尾部。"""

        if not self._dynamic_system_context:
            return
        self._dynamic_system_context = build_dynamic_system_context()
        self._base_system_prompt = (
            self._static_system_prompt + "\n\n" + self._dynamic_system_context
        )
        self._system_prompt = self._base_system_prompt

    def _refresh_memory_context_after_dream(self, filenames: list[str]) -> None:
        """丢弃旧预取，并让本会话后续请求看到 Dream 后的索引和文件内容。"""
        coordinator = getattr(self, "_session_memory_coord", None)
        if coordinator is None:
            # 保留 Agent.__new__ 形式窄单元测试的最小兼容边界。
            self._memory_coordinator.invalidate(filenames)
            self._refresh_dynamic_system_context()
            return
        coordinator._refresh_memory_context_after_dream(filenames)

    async def learn_from_current_session(self) -> str:
        """运行一次内置 Meta-Skill，并按其结论直接沉淀当前会话经验。"""
        transcript = json.dumps(
            [
                message.model_dump(mode="json", by_alias=True)
                for message in self._core_runtime.messages
            ],
            ensure_ascii=False,
            default=str,
        )
        messages = [{
            "role": "user",
            "content": f"Working directory: {Path.cwd()}\n\nCurrent session JSON:\n{transcript}",
        }]
        raw = await self._run_evaluator_query(
            LEARN_META_SKILL_PROMPT, messages, max_tokens=4096
        )

        try:
            start = raw.index("{")
            decision = json.loads(raw[start:raw.rindex("}") + 1])
        except (ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid Meta-Skill response") from exc

        if not decision.get("create"):
            return f"不建议沉淀：{decision.get('reason', '当前会话没有可复用经验')}"

        try:
            return create_skill(
                name=decision["name"],
                content=decision["content"],
                scope=decision["scope"],
            )
        except KeyError as exc:
            raise ValueError("Invalid Meta-Skill response") from exc

    # ─── /goal 追踪 ──────────────────────────────────────────
    # 每轮结束后由独立评估模型检查 Stop-hook 条件；未满足的原因进入下一轮，
    # 满足或判定不可能时停止。评估契约集中在 autonomy.py。

    @property
    def active_goal(self) -> dict | None:
        """活动目标(状态由 AutonomyRuntime 拥有)。"""
        return self._autonomy.active_goal

    @property
    def goal_stop(self) -> bool:
        return self._autonomy.goal_stop

    @property
    def pending_wakeup(self) -> dict | None:
        return self._autonomy.pending_wakeup

    @property
    def loop_stop(self) -> bool:
        return self._autonomy.loop_stop

    @property
    def auto_consecutive_denials(self) -> int:
        """Auto Mode 连续拒绝计数(状态由 AutonomyRuntime 拥有)。"""
        return self._autonomy.auto_consecutive_denials

    @property
    def auto_total_denials(self) -> int:
        return self._autonomy.auto_total_denials

    def set_goal(self, condition: str) -> str:
        """设置活动目标并返回首轮执行指令。"""
        return self._autonomy.set_goal(condition)

    def show_goal(self) -> None:
        """处理无参数 /goal,显示当前目标状态。"""
        self._autonomy.show_goal()

    async def pursue_goal(self, directive: str) -> None:
        """持续执行运行->评估->反馈,直到目标终止条件出现。"""
        await self._autonomy.pursue_goal(directive)

    def _canonical_side_messages(self, messages: list) -> list[AgentMessage]:
        """把 {role, content} 字典消息转为 canonical,供 Provider side-query。"""
        canonical: list[AgentMessage] = []
        for message in messages:
            content = str(message.get("content", ""))
            if message.get("role") == "assistant":
                canonical.append(
                    AssistantMessage(
                        model=self.model,
                        content=[TextContent(text=content)],
                        stop_reason="stop",
                    )
                )
            else:
                canonical.append(UserMessage(content=content))
        return canonical

    async def _run_evaluator_query(
        self, system: str, messages: list, max_tokens: int = 512
    ) -> str:
        """通过当前 Provider 发送保留 role 的评估请求，并返回模型文本。

        与只接受单条 user 消息的 sideQuery 分开，避免 Memory 接口限制目标评估结构。
        """
        del max_tokens
        return await complete_text(
            self._core_runtime.provider,
            model=self.model,
            system=system,
            messages=self._canonical_side_messages(messages),
        )

    async def _run_classifier_query(self, system: str, user: str, max_tokens: int) -> str:
        """通过当前 Provider 发送单消息分类请求。"""
        return await self._build_core_memory_query_service().complete(
            system=system,
            user=user,
            max_output_tokens=max_tokens,
        )

    def _extract_last_assistant_text(self) -> str:
        """提取最近一轮 assistant 文本;实现在 AutonomyRuntime。"""
        return self._autonomy._extract_last_assistant_text()

    # ─── /loop：定时或自主节奏 ───────────────────────────────
    # /goal 被动决定是否继续，/loop 则用固定间隔或 schedule_wakeup 主动安排下一轮。

    async def run_loop(self, raw_input: str) -> None:
        """解析 /loop 输入并驱动对应模式;格式错误时直接返回。"""
        await self._autonomy.run_loop(raw_input)

    async def _run_loop_dynamic(self, spec: dict) -> None:
        """动态 /loop 驱动;实现在 AutonomyRuntime,保留入口供内部测试。"""
        await self._autonomy._run_loop_dynamic(spec)

    def _execute_schedule_wakeup(self, inp: dict) -> str:
        """记录唤醒请求;由 schedule_wakeup_tool 调用,实现在 AutonomyRuntime。"""
        return self._autonomy._execute_schedule_wakeup(inp)

    def stop_loop(self) -> None:
        """通知正在运行的 /loop 在最近的检查点停止。"""
        self._autonomy.stop_loop()

    def stop_goal(self) -> None:
        """通知 /goal 在下一轮边界停止;正在进行的调用由 abort() 单独取消。"""
        self._autonomy.stop_goal()

    # ─── Auto Mode：transcript 分类器权限门 ───────────────────
    # auto 模式用分类器替代人工确认：deny 仍是硬边界，只读工具走快路径，
    # 其余动作由 LLM 根据不含推理的 transcript 投影判断。

    async def _classify_tool_call(self, tool_name: str, inp: dict) -> dict:
        """以两阶段分类器决定工具调用,返回 allow/deny/confirm。"""
        return await self._autonomy._classify_tool_call(tool_name, inp)

    def _child_api_kwargs(self) -> dict:
        """子 Agent fork 的模型与凭证参数:继承父级当前后端的 key/base。

        此前 fork 只传 api_base 不传 key,/model 配置(无环境变量)的用户
        fork 出的子 Agent 是无凭证的。
        """
        if self.use_openai:
            return {
                "model": self.model,
                "api_base": self._api_base,
                "api_key": self._api_key,
                "terminal_output": self._terminal_output,
            }
        return {
            "model": self.model,
            "api_base": None,
            "anthropic_base_url": self._anthropic_base_url,
            "api_key": self._api_key,
            "terminal_output": self._terminal_output,
        }

    def _child_permission_mode(self) -> str:
        """确定子 Agent 继承的权限模式。

        plan 与 auto 必须向下传递；否则默认 bypassPermissions 会让主模型借子 Agent
        绕过只读或分类器限制。其他模式允许子 Agent 独立执行已授权任务。
        """
        if self.permission_mode == "plan":
            return "plan"
        if self.permission_mode == "auto":
            return "auto"
        return "bypassPermissions"

    # ─── 会话持久化 ──────────────────────────────────────────

    async def restore_core_session(self, session_id: str) -> bool:
        """从 JSONL 重建 Harness 唯一历史，并继续追加同一 Session。"""
        await self._flush_background_operations()
        state = await self._session_repository.load(session_id)
        if state is None:
            return False

        self._memory_coordinator.reset()
        self._reload_project_memory()
        self._reload_session_memory()
        self._last_memory_injection = MemoryInjectionReport()
        self.session_id = session_id
        self.tool_context.session_id = session_id
        self._pending_core_context_reset = None
        self._core_compaction_required = False
        self._last_context_actions = ()
        self._core_runtime.harness.clear_queues()
        self._core_runtime.harness.replace_messages(state.messages)
        if state.model is not None:
            self.model = state.model
            self.effective_window = effective_window_tokens(
                fallback_model_limits(self.model)
            )
            self._resolved_model_limits_for = None
            self._core_runtime.set_model(self.model)
        if state.thinking_level is not None:
            restored_level = coerce_thinking_level(state.thinking_level)
            if restored_level != self._thinking_level:
                self._apply_core_thinking_level(restored_level)
        if state.session_info is not None:
            self.session_start_time = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime(state.session_info.created_at),
            )
        self._reset_core_observers()
        await self._ensure_core_session_ready()
        self._reset_session_counters()
        self._turn_memory_overlays = self._build_turn_memory_overlays()
        self._emit_notice(f"Session restored ({len(state.messages)} messages).")
        return True

    def _reload_session_memory(self) -> None:
        """重载当前项目状态；损坏文件仅暴露错误，绝不回写空状态。"""

        self._session_memory_coord._reload_session_memory()

    def _report_session_memory_error(self) -> None:
        self._session_memory_coord._report_session_memory_error()

    async def _update_session_memory_after_turn(
        self,
        user_message: str,
        turn_start_index: int,
    ) -> None:
        """保存本轮确定性工具事实，再以受限模型 patch 补充任务语义。"""

        await self._session_memory_coord._update_session_memory_after_turn(
            user_message,
            turn_start_index,
            semantic_extractor=self._extract_session_memory_semantics,
        )

    async def _extract_session_memory_semantics(
        self,
        memory: SessionMemory,
        user_message: str,
        assistant_text: str,
    ) -> dict[str, object]:
        """让 side query 只提炼目标和交接语义，不接管工具事实。"""

        return await self._session_memory_coord._extract_session_memory_semantics(
            memory,
            user_message,
            assistant_text,
        )

    async def restore_session_id(self, session_id: str) -> bool:
        """优先恢复 JSONL；Core 遇到旧 JSON 时原地迁移且保留源文件。"""
        if self._session_repository.exists(session_id):
            restored = await self.restore_core_session(session_id)
            if restored:
                return True
        legacy = load_legacy_session(
            self._session_repository.session_dir,
            session_id,
        )
        if legacy is None:
            return False
        await self._migrate_legacy_core_session(session_id, legacy)
        return await self.restore_core_session(session_id)

    async def list_sessions(self) -> list[dict[str, Any]]:
        """统一枚举新 JSONL 与尚未迁移的旧 JSON Session。"""
        current = await self._session_repository.list_sessions()
        current_ids = {str(item.get("id")) for item in current}
        legacy = [
            item
            for item in list_legacy_sessions(self._session_repository.session_dir)
            if str(item.get("id")) not in current_ids
        ]
        sessions = [*current, *legacy]
        sessions.sort(key=lambda item: str(item.get("startTime", "")), reverse=True)
        return sessions

    async def latest_session_id(self) -> str | None:
        sessions = await self.list_sessions()
        return str(sessions[0]["id"]) if sessions else None

    async def restore_latest_session(self) -> bool:
        session_id = await self.latest_session_id()
        if session_id is None:
            self._emit_notice("No previous sessions found.")
            return False
        restored = await self.restore_session_id(session_id)
        if not restored:
            self._emit_notice(f"Session {session_id} could not be restored in this runtime.")
        return restored

    async def _migrate_legacy_core_session(
        self,
        session_id: str,
        legacy: dict[str, Any],
    ) -> None:
        metadata = legacy.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        recorder = SessionRecorder(
            session_id=session_id,
            model=str(metadata.get("model") or self.model),
            thinking_level=self._thinking_level,
            cwd=Path(str(metadata.get("cwd") or self.tool_context.cwd)),
            storage=self._session_repository.storage_for(session_id),
        )
        await recorder.initialize()
        for message in legacy_session_messages(legacy):
            await recorder.record_message(message)

    def _is_snippable_tool(self, name: str) -> bool:
        try:
            tool = self.tool_registry.resolve(name)
        except LookupError:
            return False
        return tool.capabilities.result_policy == "snippable"

    # ─── 工具路由（含 Agent、Skill 与 Plan 内部工具）────────

    async def _execute_tool_call(
        self,
        name: str,
        inp: dict,
        tool_call_id: str = "",
    ) -> str:
        self.tool_context.permission_mode = self.permission_mode
        self.tool_context.plan_file_path = self._plan_file_path
        result = await self.tool_runtime.execute(
            tool_call_id=tool_call_id,
            name=name,
            arguments=inp,
        )
        return result.content

    async def run_subagent_tool(
        self,
        arguments: Mapping[str, JSONValue],
    ) -> ToolResult:
        """向 agent 工具暴露受限的子 Agent 业务入口。"""
        return ToolResult(content=await self._execute_agent_tool(dict(arguments)))

    async def run_skill_tool(
        self,
        arguments: Mapping[str, JSONValue],
    ) -> ToolResult:
        """向 skill 工具暴露受限的 Skill 业务入口。"""
        return ToolResult(content=await self._execute_skill_tool(dict(arguments)))

    async def enter_plan_mode_tool(self) -> ToolResult:
        """进入 Plan 模式并返回结构化工具结果。"""
        return ToolResult(
            content=await self._execute_plan_mode_tool("enter_plan_mode")
        )

    async def exit_plan_mode_tool(self) -> ToolResult:
        """退出 Plan 模式并返回结构化工具结果。"""
        content = await self._execute_plan_mode_tool("exit_plan_mode")
        return ToolResult(
            content=content,
            terminate=self._pending_core_context_reset is not None,
        )

    async def schedule_wakeup_tool(
        self,
        arguments: Mapping[str, JSONValue],
    ) -> ToolResult:
        """记录动态循环的下一次唤醒请求。"""
        return ToolResult(content=self._execute_schedule_wakeup(dict(arguments)))

    # ─── Skill fork 模式 ─────────────────────────────────────

    async def _execute_skill_tool(self, inp: dict) -> str:
        from .skills import execute_skill
        result = execute_skill(inp.get("skill_name", ""), inp.get("args", ""))
        if not result:
            return f"Unknown skill: {inp.get('skill_name', '')}"

        if result["context"] == "fork":
            self._emit_subagent_status(
                "skill-fork", inp.get("skill_name", ""), started=True
            )
            sub_agent = self._subagent_factory.create_for_skill(
                system_prompt=result["prompt"],
                allowed_tools=result.get("allowed_tools"),
            )
            try:
                sub_result = await sub_agent.run_once(inp.get("args") or "Execute this skill task.")
                self.total_input_tokens += sub_result["tokens"]["input"]
                self.total_output_tokens += sub_result["tokens"]["output"]
                self._emit_subagent_status(
                    "skill-fork", inp.get("skill_name", ""), started=False
                )
                return sub_result["text"] or "(Skill produced no output)"
            except Exception as e:
                self._emit_subagent_status(
                    "skill-fork", inp.get("skill_name", ""), started=False
                )
                return f"Skill fork error: {e}"
            finally:
                await sub_agent.close()

        return f'[Skill "{inp.get("skill_name", "")}" activated]\n\n{result["prompt"]}'

    # ─── Plan 模式辅助 ───────────────────────────────────────

    def _generate_plan_file_path(self) -> str:
        d = Path.home() / ".claude" / "plans"
        d.mkdir(parents=True, exist_ok=True)
        return str(d / f"plan-{self.session_id}.md")

    def _build_plan_mode_prompt(self) -> str:
        return f"""

# Plan Mode Active

Plan mode is active. You MUST NOT make any edits (except the plan file below), run non-readonly tools, or make any changes to the system.

## Plan File: {self._plan_file_path}
Write your plan incrementally to this file using write_file or edit_file. This is the ONLY file you are allowed to edit.

## Workflow
1. **Explore**: Read code to understand the task. Use read_file, list_files, grep_search.
2. **Design**: Design your implementation approach. Use the agent tool with type="plan" if the task is complex.
3. **Write Plan**: Write a structured plan to the plan file including:
   - **Context**: Why this change is needed
   - **Steps**: Implementation steps with critical file paths
   - **Verification**: How to test the changes
4. **Exit**: Call exit_plan_mode when your plan is ready for user review.

IMPORTANT: When your plan is complete, you MUST call exit_plan_mode. Do NOT ask the user to approve — exit_plan_mode handles that."""

    async def _execute_plan_mode_tool(self, name: str) -> str:
        if name == "enter_plan_mode":
            if self.permission_mode == "plan":
                return "Already in plan mode."
            self._pre_plan_mode = self.permission_mode
            self.permission_mode = "plan"
            self._plan_file_path = self._generate_plan_file_path()
            self._system_prompt = self._base_system_prompt + self._build_plan_mode_prompt()
            self.tool_context.permission_mode = self.permission_mode
            self.tool_context.plan_file_path = self._plan_file_path
            self._emit_notice("Entered plan mode (read-only). Plan file: " + self._plan_file_path)
            return f"Entered plan mode. You are now in read-only mode.\n\nYour plan file: {self._plan_file_path}\nWrite your plan to this file. This is the only file you can edit.\n\nWhen your plan is complete, call exit_plan_mode."

        if name == "exit_plan_mode":
            if self.permission_mode != "plan":
                return "Not in plan mode."
            plan_content = "(No plan file found)"
            if self._plan_file_path and Path(self._plan_file_path).exists():
                plan_content = Path(self._plan_file_path).read_text()

            # 主 Agent 有审批回调时进入交互式选择流程。
            if self._plan_approval_fn:
                result = await self._plan_approval_fn(plan_content)
                choice = result.get("choice", "manual-execute")

                if choice == "keep-planning":
                    feedback = result.get("feedback") or "Please revise the plan."
                    return (
                        f"User rejected the plan and wants to keep planning.\n\n"
                        f"User feedback: {feedback}\n\n"
                        f"Please revise your plan based on this feedback. When done, call exit_plan_mode again."
                    )

                # 根据用户选择确定退出 Plan 后的权限模式。
                if choice == "clear-and-execute":
                    target_mode = "acceptEdits"
                elif choice == "execute":
                    target_mode = "acceptEdits"
                else:  # 手动审批编辑时恢复进入 Plan 前的模式。
                    target_mode = self._pre_plan_mode or "default"

                # 先完整退出 Plan，再把批准后的计划交回模型执行。
                self.permission_mode = target_mode
                self._pre_plan_mode = None
                saved_plan_path = self._plan_file_path
                self._plan_file_path = None
                self._system_prompt = self._base_system_prompt
                self.tool_context.permission_mode = self.permission_mode
                self.tool_context.plan_file_path = self._plan_file_path

                if choice == "clear-and-execute":
                    self._pending_core_context_reset = (
                        f"Approved plan:\n{plan_content}\n\n"
                        "Proceed with implementation."
                    )
                    self._emit_notice(f"Plan approved. Context cleared, executing in {target_mode} mode.")
                    return (
                        f"User approved the plan. Context was cleared. Permission mode: {target_mode}\n\n"
                        f"Plan file: {saved_plan_path}\n\n"
                        f"## Approved Plan:\n{plan_content}\n\n"
                        f"Proceed with implementation."
                    )

                self._emit_notice(f"Plan approved. Executing in {target_mode} mode.")
                return (
                    f"User approved the plan. Permission mode: {target_mode}\n\n"
                    f"## Approved Plan:\n{plan_content}\n\n"
                    f"Proceed with implementation."
                )

            # 子 Agent 等无审批回调场景直接恢复原权限模式，不伪造用户批准。
            self.permission_mode = self._pre_plan_mode or "default"
            self._pre_plan_mode = None
            self._plan_file_path = None
            self._system_prompt = self._base_system_prompt
            self.tool_context.permission_mode = self.permission_mode
            self.tool_context.plan_file_path = self._plan_file_path
            self._emit_notice("Exited plan mode. Restored to " + self.permission_mode + " mode.")
            return f"Exited plan mode. Permission mode restored to: {self.permission_mode}\n\n## Your Plan:\n{plan_content}"

        return f"Unknown plan mode tool: {name}"

    async def _execute_agent_tool(self, inp: dict) -> str:
        agent_type = inp.get("type", "general")
        description = inp.get("description", "sub-agent task")
        prompt = inp.get("prompt", "")

        self._emit_subagent_status(agent_type, description, started=True)

        sub_agent = self._subagent_factory.create_for_agent_type(agent_type)

        try:
            result = await sub_agent.run_once(prompt)
            self.total_input_tokens += result["tokens"]["input"]
            self.total_output_tokens += result["tokens"]["output"]
            self._emit_subagent_status(agent_type, description, started=False)
            return result["text"] or "(Sub-agent produced no output)"
        except Exception as e:
            self._emit_subagent_status(agent_type, description, started=False)
            return f"Sub-agent error: {e}"
        finally:
            await sub_agent.close()

    # ─── 外部资源与 Memory 预取 ──────────────────────────────

    async def close(self) -> None:
        """释放 MCP 子进程等外部资源，确保进程正常退出（issue #8）。"""
        try:
            await self._flush_background_operations()
        finally:
            try:
                await self._memory_coordinator.close()
            finally:
                try:
                    await self._core_runtime.aclose()
                finally:
                    await self.tool_environment.close()

    async def _confirm_hook_trust(self, message: str) -> bool:
        # 项目 Hook 信任独立于工具权限；--yolo 也不能替仓库代码自动取得信任。
        if self.permission_mode == "dontAsk":
            return False
        return await self._confirm_dangerous(message)

    async def _confirm_dangerous(self, command: str) -> bool:
        if self._terminal_output:
            print_confirmation(command)
        if self.confirm_fn:
            return await self.confirm_fn(command)
        # 无异步回调时退回阻塞式终端输入，仅用于直接嵌入 Agent 的场景。
        try:
            answer = input("  Allow? (y/n): ")
            return answer.lower().startswith("y")
        except EOFError:
            return False
