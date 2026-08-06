"""Agent 核心循环：统一 Anthropic 与 OpenAI 兼容后端的流式调用、上下文压缩、
Plan 模式、子 Agent、权限与预算控制。整体分层参考 Claude Code 的公开设计。
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import Awaitable, Callable, Coroutine, Mapping
from pathlib import Path
from typing import Any, Literal

from .agent_lifecycle import AgentLifecycle
from .agent_runtime import (
    AgentRunResult,
    AgentRuntimeCoordinator,
    LionAgentRuntime,
)
from .autonomy_runtime import AutonomyRuntime
from .context import (
    ContextCompactor,
    ContextManager,
    ModelLimitsResolver,
    effective_window_tokens,
    fallback_model_limits,
)
from .core.messages import AgentMessage, AssistantMessage, TextContent, UserMessage
from .core.provider import ModelProvider
from .hooks import load_pre_tool_use_hooks
from .learning_runtime import (
    LEARN_META_SKILL_PROMPT,  # noqa: F401
    LearningRuntime,
)
from .memory_runtime import (
    MemoryContextInjector,
    MemoryCoordinator,
    MemoryInjectionReport,
    MemoryOverlay,
)
from .observers import TerminalRenderer
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

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_read_tokens = 0  # Prompt cache 命中按约 0.1 倍计费。
        self.total_cache_creation_tokens = 0  # Prompt cache 写入按约 1.25 倍计费。
        self.last_input_token_count = 0
        self.current_turns = 0
        self.last_api_call_time = 0.0

        # /goal、/loop 与 Auto Mode 的状态和协调循环由 AutonomyRuntime 拥有。
        self._autonomy = AutonomyRuntime(self)
        self._learning = LearningRuntime(self)

        # 当前异步任务用于把 Ctrl+C 传播到正在等待的模型或工具调用。
        self._aborted = False
        self._current_task: asyncio.Task | None = None
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
        runtime_context_manager = context_manager or ContextManager(
            is_snippable_tool=self._is_snippable_tool
        )

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
            if self._dynamic_system_context
            else self._static_system_prompt
        )
        if self.permission_mode == "plan":
            self._plan_file_path = self._generate_plan_file_path()
            self._system_prompt = (
                self._base_system_prompt + self._build_plan_mode_prompt()
            )
        else:
            self._system_prompt = self._base_system_prompt

        self._lifecycle = AgentLifecycle(self)
        provider = self._lifecycle.build_core_provider(self._thinking_level)
        self._runtime_coordinator = AgentRuntimeCoordinator(
            self,
            provider=provider,
            model=self.model,
            tool_runtime=self.tool_runtime,
            context_manager=runtime_context_manager,
            context_compactor=context_compactor,
            model_limits_resolver=model_limits_resolver or ModelLimitsResolver(),
        )
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
    def _core_runtime(self) -> LionAgentRuntime:
        """兼容暴露唯一 Core Runtime；实际所有权在运行时协调器。"""

        return self._runtime_coordinator.core_runtime

    @_core_runtime.setter
    def _core_runtime(self, value: LionAgentRuntime) -> None:
        self._runtime_coordinator.core_runtime = value

    @property
    def _session_recorder(self) -> SessionRecorder | None:
        return self._runtime_coordinator.session_recorder

    @_session_recorder.setter
    def _session_recorder(self, value: SessionRecorder | None) -> None:
        self._runtime_coordinator.session_recorder = value

    @property
    def _context_compactor(self) -> ContextCompactor | None:
        return self._runtime_coordinator.context_compactor

    @_context_compactor.setter
    def _context_compactor(self, value: ContextCompactor | None) -> None:
        self._runtime_coordinator.context_compactor = value

    @property
    def _context_manager(self) -> ContextManager:
        return self._runtime_coordinator.context_manager

    @property
    def _resolved_model_limits_for(self) -> tuple[int, str] | None:
        return self._runtime_coordinator.resolved_model_limits_for

    @_resolved_model_limits_for.setter
    def _resolved_model_limits_for(self, value: tuple[int, str] | None) -> None:
        self._runtime_coordinator.resolved_model_limits_for = value

    @property
    def _core_compaction_required(self) -> bool:
        return self._runtime_coordinator.core_compaction_required

    @_core_compaction_required.setter
    def _core_compaction_required(self, value: bool) -> None:
        self._runtime_coordinator.core_compaction_required = value

    @property
    def _usage_observer(self):
        return self._runtime_coordinator.usage_observer

    @_usage_observer.setter
    def _usage_observer(self, value: Any) -> None:
        self._runtime_coordinator.usage_observer = value

    @property
    def _terminal_renderer(self) -> TerminalRenderer | None:
        return self._runtime_coordinator.terminal_renderer

    def _create_terminal_renderer(self) -> TerminalRenderer:
        """在调用时读取本模块 Renderer，保留既有动态 patch 锚点。"""

        return TerminalRenderer()

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

    def _load_project_context_files(self, identity: ProjectIdentity) -> tuple[Any, ...]:
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
        self._session_memory_coord.session_memory = value

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
        return self._session_memory_coord.memory_coordinator

    @_memory_coordinator.setter
    def _memory_coordinator(self, value: Any) -> None:
        self._session_memory_coord.memory_coordinator = value

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
        self._runtime_coordinator.abort()

    # ─── Core Runtime ────────────────────────────────────────

    def _sync_core_usage(self) -> None:
        self._runtime_coordinator.sync_core_usage()

    async def _ensure_core_session_ready(self) -> None:
        await self._runtime_coordinator.ensure_core_session_ready()

    async def compact_core_context_for_overflow(self) -> bool:
        return await self._runtime_coordinator.compact_core_context_for_overflow()

    def _schedule_background_operation(
        self,
        operation: Callable[[], Coroutine[Any, Any, object]],
    ) -> None:
        self._runtime_coordinator.schedule_background_operation(operation)

    def set_terminal_output(self, enabled: bool) -> None:
        self._runtime_coordinator.set_terminal_output(enabled)

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

    def set_plan_approval_fn(self, fn: Callable[[str], Awaitable[dict]] | None) -> None:
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
            self._system_prompt = (
                self._base_system_prompt + self._build_plan_mode_prompt()
            )
            self.tool_context.permission_mode = self.permission_mode
            self.tool_context.plan_file_path = self._plan_file_path
            self._emit_notice(f"Entered plan mode. Plan file: {self._plan_file_path}")
            return "plan"

    def get_token_usage(self) -> dict:
        return {"input": self.total_input_tokens, "output": self.total_output_tokens}

    # ─── 运行时模型/凭证配置（TUI /model 的后端）──────────────

    @property
    def api_configured(self) -> bool:
        return self._lifecycle.api_configured

    def get_api_config(self) -> dict:
        """返回 Agent 自己持有的当前 Provider 配置。"""
        return self._lifecycle.get_api_config()

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
        self._lifecycle.configure_api(
            model=model,
            api_key=api_key,
            api_base=api_base,
            anthropic_base_url=anthropic_base_url,
            use_openai=use_openai,
        )

    def set_thinking(self, enabled: bool) -> str:
        """切换 Thinking，并把实际生效级别写入当前 Core Session。"""
        return self._lifecycle.set_thinking(enabled)

    # ─── Core 路径 Thinking 档位(Tau 6 档)─────────────────────

    @property
    def thinking_level(self) -> str:
        """Core 路径当前 thinking 档位(off..xhigh)。"""
        return self._lifecycle.thinking_level

    @property
    def available_thinking_levels(self) -> tuple[str, ...]:
        """当前后端支持的 thinking 档位(v1 两后端均返回全 6 档)。"""
        return self._lifecycle.available_thinking_levels

    def set_thinking_level(self, level: ThinkingLevel | str) -> ThinkingLevel:
        """设定 thinking 档位并热重建 Core Provider,持久化档位变更。

        与布尔 ``set_thinking(bool)`` 接口互不影响:本方法采用
        Tau 6 档词汇;档位经归一化,未变则直接返回,不重建不落盘。
        """
        return self._lifecycle.set_thinking_level(level)

    def cycle_thinking_level(self) -> ThinkingLevel:
        """循环到下一档并持久化(供 TUI shift+tab 与 /thinking 无参调用)。"""
        return self._lifecycle.cycle_thinking_level()

    def _build_core_provider(self, thinking_level: ThinkingLevel) -> ModelProvider:
        """用当前凭证与指定档位构建一个新 Core Provider。"""
        return self._lifecycle.build_core_provider(thinking_level)

    def _create_provider(self, **kwargs: Any) -> ModelProvider:
        """在调用时读取本模块 factory，保留测试替身的动态 patch 锚点。"""
        return create_provider(**kwargs)

    def _apply_core_thinking_level(self, level: ThinkingLevel) -> None:
        """设定 ``self._thinking_level`` 并热重建 Core Provider 使档位生效。

        不落盘档位变更(由调用方按需记录):恢复会话时复用本方法仅重建 Provider,
        避免对已有 entry 重复写。``context_compactor`` 与模型限制缓存一并刷新。
        """
        self._lifecycle.apply_core_thinking_level(level)

    # ─── 主对话入口 ──────────────────────────────────────────

    async def _ensure_mcp_tools(self) -> None:
        """仅由根 Agent 首次发现 MCP；失败作为 notice，不中断 Core 对话。"""

        if (
            not self._mcp_enabled
            or self._mcp_initialized
            or self.is_sub_agent
            or not self.tool_environment.owns_mcp_manager
        ):
            return
        self._mcp_initialized = True
        try:
            definitions = await self._mcp_manager.discover_tools()
            for definition in definitions:
                self.tool_registry.register(create_mcp_tool(self._mcp_manager, definition))
        except Exception as error:
            self._emit_notice(f"[mcp] Init failed: {error}")

    async def chat(self, user_message: str) -> None:
        await self._runtime_coordinator.chat(user_message)

    # ─── 子 Agent 单次运行入口 ───────────────────────────────

    async def run_once(self, prompt: str) -> dict:
        return await self._runtime_coordinator.run_once(prompt)

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
        return await self._runtime_coordinator.run(prompt, timeout=timeout)

    # ─── REPL 命令状态 ───────────────────────────────────────

    async def clear_history(self) -> None:
        """结束当前会话并创建新 Session；旧 append-only 历史保持可恢复。"""
        await self._runtime_coordinator.clear_history()

    def show_cost(self) -> None:
        total = self._get_current_cost_usd()
        budget_info = f" / ${self.max_cost_usd} budget" if self.max_cost_usd else ""
        turn_info = (
            f" | Turns: {self.current_turns}/{self.max_turns}" if self.max_turns else ""
        )
        cached = self.total_cache_read_tokens
        billed_input = (
            self.total_input_tokens + self.total_cache_creation_tokens + cached
        )
        hit_rate = round((cached / billed_input) * 100) if billed_input > 0 else 0
        cache_info = (
            f"\n  Cache: {cached} read / {self.total_cache_creation_tokens} write ({hit_rate}% of input from cache)"
            if (cached or self.total_cache_creation_tokens)
            else ""
        )
        self._emit_notice(
            f"Tokens: {self.total_input_tokens} in / {self.total_output_tokens} out{cache_info}\n  Estimated cost: ${total:.4f}{budget_info}{turn_info}"
        )

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
        if (
            self.max_cost_usd is not None
            and self._get_current_cost_usd() >= self.max_cost_usd
        ):
            return {
                "exceeded": True,
                "kind": "max_cost",
                "reason": f"Cost limit reached (${self._get_current_cost_usd():.4f} >= ${self.max_cost_usd})",
            }
        if self.max_turns is not None and self.current_turns >= self.max_turns:
            return {
                "exceeded": True,
                "kind": "max_turns",
                "reason": f"Turn limit reached ({self.current_turns} >= {self.max_turns})",
            }
        return {"exceeded": False}

    async def compact(self) -> None:
        await self._runtime_coordinator.compact()

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
        self._session_memory_coord._refresh_memory_context_after_dream(filenames)

    async def learn_from_current_session(self) -> str:
        """运行一次内置 Meta-Skill，并按其结论直接沉淀当前会话经验。"""
        return await self._learning.learn_from_current_session()

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

    async def _run_classifier_query(
        self, system: str, user: str, max_tokens: int
    ) -> str:
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
        return await self._runtime_coordinator.restore_core_session(session_id)

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
            self._emit_notice(
                f"Session {session_id} could not be restored in this runtime."
            )
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
        return ToolResult(content=await self._execute_plan_mode_tool("enter_plan_mode"))

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
                sub_result = await sub_agent.run_once(
                    inp.get("args") or "Execute this skill task."
                )
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
            self._system_prompt = (
                self._base_system_prompt + self._build_plan_mode_prompt()
            )
            self.tool_context.permission_mode = self.permission_mode
            self.tool_context.plan_file_path = self._plan_file_path
            self._emit_notice(
                "Entered plan mode (read-only). Plan file: " + self._plan_file_path
            )
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
                    self._emit_notice(
                        f"Plan approved. Context cleared, executing in {target_mode} mode."
                    )
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
            self._emit_notice(
                "Exited plan mode. Restored to " + self.permission_mode + " mode."
            )
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
        await self._runtime_coordinator.close()

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
