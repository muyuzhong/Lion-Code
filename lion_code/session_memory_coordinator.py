"""Session Memory、Memory Overlay 与 Dream 的运行时协调层。

``SessionMemoryCoordinator`` 只拥有项目短期状态和 Memory 召回状态，通过
``SessionMemoryHost`` 回调 Agent 的 Core、Provider 与界面通知能力。这样 Agent
仍负责运行时组装和 canonical history，而新增或修改 Memory 功能不必再穿透
Goal、Provider 切换和 TUI 输出。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any, Literal, Protocol, cast, runtime_checkable

from .core.messages import AgentMessage, AssistantMessage
from .memory_runtime import (
    MemoryContextInjector,
    MemoryCoordinator,
    MemoryInjectionReport,
    MemoryOverlay,
    ProviderTextQueryService,
)
from .project_identity import ProjectIdentity
from .session_memory import (
    SessionMemory,
    SessionMemoryError,
    SessionMemoryRepository,
    apply_semantic_patch,
    apply_tool_evidence,
    build_handoff,
    extract_long_term_candidates,
    extract_tool_evidence,
    finish_active_task,
    format_active_task,
    format_session_memory,
    switch_active_task,
)

SESSION_MEMORY_EXTRACTION_SYSTEM = """You maintain a coding agent's short-lived project work state. Return exactly one JSON object, with no Markdown.

You may use only these optional keys: currentGoal, activeTask, completed, pending, decisions, blockers, previousHandoff, nextStep.

Use concise strings. completed, pending, decisions, and blockers must be arrays of strings. Do not include relevantFiles or verification: they are extracted deterministically. Do not invent test outcomes, file changes, or work that is not supported by the supplied evidence."""


@runtime_checkable
class SessionMemoryHost(Protocol):
    """协调器使用的 Agent 窄协议，不持有 Provider 或 TUI。"""

    _aborted: bool
    _core_runtime: Any
    _session_repository: Any
    is_sub_agent: bool
    model: str
    permission_mode: str
    tool_environment: Any
    tool_registry: Any
    total_input_tokens: int
    total_output_tokens: int
    tool_context: Any

    def _child_api_kwargs(self) -> dict[str, Any]: ...

    def _emit_notice(
        self, message: str, *, role: Literal["info", "error"] = "info"
    ) -> None: ...

    def _emit_subagent_status(
        self, agent_type: str, description: str, *, started: bool
    ) -> None: ...

    def _refresh_dynamic_system_context(self) -> None: ...

    def _load_project_context_files(
        self, identity: ProjectIdentity
    ) -> tuple[Any, ...]: ...


def _turn_assistant_text(messages: tuple[AgentMessage, ...]) -> str:
    return next(
        (
            message.text
            for message in reversed(messages)
            if isinstance(message, AssistantMessage)
        ),
        "",
    )


def _trim_session_memory_text(text: str, limit: int = 4_000) -> str:
    return text[:limit] + ("…" if len(text) > limit else "")


def _parse_session_memory_patch(raw: str) -> dict[str, object]:
    candidate = raw.strip()
    if not candidate:
        return {}
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


SemanticExtractor = Callable[[SessionMemory, str, str], Awaitable[dict[str, object]]]


class SessionMemoryCoordinator:
    """拥有项目级 Session Memory 与三层 Overlay 的协调器。"""

    def __init__(
        self,
        host: SessionMemoryHost,
        *,
        identity: ProjectIdentity,
        repository: SessionMemoryRepository | None = None,
    ) -> None:
        self._host = host
        self._project_identity = identity
        self._session_memory_repository = repository or SessionMemoryRepository(
            identity
        )
        if self._session_memory_repository.identity != identity:
            raise ValueError("Session Memory repository belongs to another project")

        self._project_context_files: tuple[Any, ...] = ()
        self._project_memory_overlays: tuple[MemoryOverlay, ...] = ()
        self._session_memory: SessionMemory | None = None
        self._session_memory_error: str | None = None
        self._reported_session_memory_error: str | None = None
        self._memory_coordinator: Any = MemoryCoordinator(query_service=None)
        self._memory_injector = MemoryContextInjector()
        self._last_memory_injection = MemoryInjectionReport()
        self._turn_memory_overlays: tuple[MemoryOverlay, ...] = ()

        self._reload_project_memory()
        self._reload_session_memory()
        self._turn_memory_overlays = self._build_turn_memory_overlays()

    @property
    def project_identity(self) -> ProjectIdentity:
        return self._project_identity

    @property
    def session_memory_repository(self) -> SessionMemoryRepository:
        return self._session_memory_repository

    @property
    def project_context_files(self) -> tuple[Any, ...]:
        return self._project_context_files

    @property
    def project_memory_overlays(self) -> tuple[MemoryOverlay, ...]:
        return self._project_memory_overlays

    @property
    def session_memory(self) -> SessionMemory | None:
        return self._session_memory

    @session_memory.setter
    def session_memory(self, value: SessionMemory | None) -> None:
        self._session_memory = value

    @property
    def session_memory_error(self) -> str | None:
        return self._session_memory_error

    @session_memory_error.setter
    def session_memory_error(self, value: str | None) -> None:
        self._session_memory_error = value

    @property
    def reported_session_memory_error(self) -> str | None:
        return self._reported_session_memory_error

    @property
    def memory_coordinator(self) -> Any:
        return self._memory_coordinator

    @memory_coordinator.setter
    def memory_coordinator(self, value: Any) -> None:
        self._memory_coordinator = value

    @property
    def memory_injector(self) -> MemoryContextInjector:
        return self._memory_injector

    @property
    def last_memory_injection(self) -> MemoryInjectionReport:
        return self._last_memory_injection

    @last_memory_injection.setter
    def last_memory_injection(self, value: MemoryInjectionReport) -> None:
        self._last_memory_injection = value

    @property
    def turn_memory_overlays(self) -> tuple[MemoryOverlay, ...]:
        return self._turn_memory_overlays

    @turn_memory_overlays.setter
    def turn_memory_overlays(self, value: tuple[MemoryOverlay, ...]) -> None:
        self._turn_memory_overlays = value

    def set_query_service(self, service: ProviderTextQueryService | None) -> None:
        """绑定当前 Core Provider 的 side-query，并取消旧 Provider 的预取。"""

        self._memory_coordinator.set_query_service(service)

    def show_session_memory(self) -> str:
        """读取并展示当前项目短期状态，不触碰 JSONL transcript。"""

        return format_session_memory(self._editable_session_memory())

    def show_active_task(self) -> str:
        """读取活动任务的最小视图。"""

        return format_active_task(self._editable_session_memory())

    def switch_session_task(self, task: str) -> str:
        """持久化新的活动任务，并把旧任务保留为待继续事项。"""

        memory = switch_active_task(self._editable_session_memory(), task)
        self._save_session_memory(memory)
        return f"已切换活动任务：{memory.active_task}"

    def finish_session_task(self) -> str:
        """结束当前任务并计算受限的长期候选，候选不会直接写入 Auto Memory。"""

        memory = self._editable_session_memory()
        if not memory.active_task:
            return "当前没有活动任务。"
        finished = memory.active_task
        memory = finish_active_task(memory)
        self._save_session_memory(memory)
        candidate_count = len(extract_long_term_candidates(memory))
        if candidate_count:
            return (
                f"已结束任务：{finished}；已准备 {candidate_count} 条长期候选，"
                "可用 /dream 复核整理。"
            )
        return f"已结束任务：{finished}；没有可安全沉淀的长期候选。"

    def create_session_handoff(self) -> str:
        """从当前短期状态生成并保存 handoff，供下一会话直接续接。"""

        memory = self._editable_session_memory()
        handoff = build_handoff(memory)
        self._save_session_memory(replace(memory, previous_handoff=handoff))
        return handoff

    def _editable_session_memory(self) -> SessionMemory:
        """重载可安全写入的项目状态；损坏文件绝不被命令覆盖。"""

        self._reload_session_memory()
        if self._session_memory_error is not None:
            raise RuntimeError(f"Session Memory 不可用：{self._session_memory_error}")
        if self._session_memory is None:
            raise RuntimeError("Session Memory 尚未初始化。")
        return self._session_memory

    def _save_session_memory(self, memory: SessionMemory) -> None:
        """保存命令产生的短期状态，不改动当前轮已固定的 Overlay。"""

        try:
            self._session_memory = self._session_memory_repository.save(memory)
            self._session_memory_error = None
        except SessionMemoryError as error:
            self._session_memory_error = str(error)
            raise RuntimeError(f"Session Memory 保存失败：{error}") from error

    def _reload_project_memory(self) -> None:
        """重新读取当前项目指令，始终保持在人写文件的只读边界内。"""

        self._project_context_files = self._host._load_project_context_files(
            self._project_identity
        )
        self._project_memory_overlays = tuple(
            MemoryOverlay(
                path=item.path,
                content=item.content,
                byte_size=len(item.content.encode("utf-8")),
                source="project",
                required=True,
            )
            for item in self._project_context_files
        )

    def _build_turn_memory_overlays(self) -> tuple[MemoryOverlay, ...]:
        """组合本轮不可变的项目、Session 与 Auto Memory。"""

        overlays = list(self._project_memory_overlays)
        if self._session_memory is not None:
            content = format_session_memory(self._session_memory)
            overlays.append(
                MemoryOverlay(
                    path=str(self._session_memory_repository.path),
                    content=content,
                    byte_size=len(content.encode("utf-8")),
                    source="session",
                    required=True,
                )
            )
        overlays.extend(self._memory_coordinator.active_overlays)
        return tuple(overlays)

    def _prepare_turn_memory_snapshot(self, user_message: str) -> None:
        """压缩后固定三层 Overlay，当前预取结果只留给下一轮。"""

        if not self._host.is_sub_agent:
            self._reload_session_memory()
            self._report_session_memory_error()
            self._memory_coordinator.collect_ready()
            self._memory_coordinator.begin_turn(user_message)
        self._turn_memory_overlays = self._build_turn_memory_overlays()

    def _build_core_memory_query_service(self) -> ProviderTextQueryService:
        """构建绑定当前 Core Provider 的文本查询服务。"""

        return ProviderTextQueryService(
            provider=self._host._core_runtime.provider,
            model=lambda: self._host.model,
        )

    def _reload_session_memory(self) -> None:
        """重载当前项目状态；损坏文件仅暴露错误，绝不回写空状态。"""

        try:
            self._session_memory = self._session_memory_repository.load()
            self._session_memory_error = None
            self._reported_session_memory_error = None
        except SessionMemoryError as error:
            self._session_memory_error = str(error)

    def _report_session_memory_error(self) -> None:
        error = self._session_memory_error
        if error is None or error == self._reported_session_memory_error:
            return
        self._reported_session_memory_error = error
        self._host._emit_notice(f"Session Memory unavailable: {error}", role="error")

    async def _update_session_memory_after_turn(
        self,
        user_message: str,
        turn_start_index: int,
        *,
        semantic_extractor: SemanticExtractor | None = None,
    ) -> None:
        """保存本轮确定性工具事实，再以受限模型 patch 补充任务语义。"""

        if self._session_memory is None or self._session_memory_error is not None:
            return
        messages = self._host._core_runtime.messages[turn_start_index:]
        if not messages:
            return
        memory = apply_tool_evidence(
            self._session_memory,
            extract_tool_evidence(messages),
        )
        if not self._host._aborted:
            try:
                extractor = semantic_extractor or self._extract_session_memory_semantics
                patch = await extractor(
                    memory,
                    user_message,
                    _turn_assistant_text(messages),
                )
            except Exception:
                patch = {}
            memory = apply_semantic_patch(memory, patch)
        try:
            self._session_memory = self._session_memory_repository.save(memory)
        except SessionMemoryError as error:
            self._session_memory_error = str(error)

    async def _extract_session_memory_semantics(
        self,
        memory: SessionMemory,
        user_message: str,
        assistant_text: str,
    ) -> dict[str, object]:
        """让 side query 只提炼目标和交接语义，不接管工具事实。"""

        payload = {
            "currentState": memory.to_dict(),
            "userInput": _trim_session_memory_text(user_message),
            "finalAssistantReply": _trim_session_memory_text(assistant_text),
        }
        raw = await self._build_core_memory_query_service().complete(
            system=SESSION_MEMORY_EXTRACTION_SYSTEM,
            user=json.dumps(payload, ensure_ascii=False),
            max_output_tokens=512,
        )
        return _parse_session_memory_patch(raw)

    async def dream(self) -> str:
        """显式整合当前项目 Memory，并返回本次文件变更摘要。"""

        if self._host.permission_mode == "plan":
            raise RuntimeError("Plan 模式为只读，退出后才能执行 /dream")

        # 延迟导入以避免 dream.py 的 Agent 类型导入与本模块形成循环依赖。
        from .dream import DreamCoordinator

        self._reload_session_memory()
        self._report_session_memory_error()
        self._host._emit_subagent_status(
            "dream", "consolidate project memory", started=True
        )
        try:
            result = await DreamCoordinator(cast(Any, self._host)).run()
        finally:
            self._host._emit_subagent_status(
                "dream", "consolidate project memory", started=False
            )
        if result.created or result.updated or result.deleted:
            self._refresh_memory_context_after_dream(
                result.created + result.updated + result.deleted
            )
        return result.summary()

    def _refresh_memory_context_after_dream(self, filenames: list[str]) -> None:
        """丢弃旧预取，并让后续请求看到 Dream 后的索引和文件内容。"""

        self._memory_coordinator.invalidate(filenames)
        self._host._refresh_dynamic_system_context()

    async def close(self) -> None:
        """关闭 Memory 预取，避免退出时留下异步任务。"""

        await self._memory_coordinator.close()
