"""Session Memory 与 Memory Overlay 的运行时协调层。

协调器只接收 canonical transcript、query、状态只读视图和具名命令，不持有
Agent、Provider、Tool Runtime 或界面实现。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import replace

from .core.cancellation import CancellationView
from .core.messages import AgentMessage, AssistantMessage
from .domain_ports import NoticeSink, TranscriptView
from .memory_runtime import (
    MemoryContextInjector,
    MemoryCoordinator,
    MemoryInjectionReport,
    MemoryOverlay,
    TextQueryService,
)
from .project_identity import ProjectIdentity
from .prompt import ProjectContextFile
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


class SessionMemoryCoordinator:
    """拥有项目级 Session Memory 与三层 Overlay 的协调器。"""

    def __init__(
        self,
        *,
        identity: ProjectIdentity,
        repository: SessionMemoryRepository | None = None,
        transcript: TranscriptView,
        cancellation: CancellationView,
        load_project_context: Callable[
            [ProjectIdentity], tuple[ProjectContextFile, ...]
        ],
        notices: NoticeSink,
        query: TextQueryService | None,
        is_sub_agent: bool,
    ) -> None:
        self._project_identity = identity
        self._session_memory_repository = repository or SessionMemoryRepository(
            identity
        )
        if self._session_memory_repository.identity != identity:
            raise ValueError("Session Memory repository belongs to another project")

        self._transcript = transcript
        self._cancellation = cancellation
        self._load_project_context = load_project_context
        self._notices = notices
        self._query = query
        self._is_sub_agent = is_sub_agent
        self._project_context_files: tuple[ProjectContextFile, ...] = ()
        self._project_memory_overlays: tuple[MemoryOverlay, ...] = ()
        self._session_memory: SessionMemory | None = None
        self._session_memory_error: str | None = None
        self._reported_session_memory_error: str | None = None
        self._memory_coordinator = MemoryCoordinator(query_service=query)
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
    def project_context_files(self) -> tuple[ProjectContextFile, ...]:
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
    def memory_coordinator(self) -> MemoryCoordinator:
        return self._memory_coordinator

    @memory_coordinator.setter
    def memory_coordinator(self, value: MemoryCoordinator) -> None:
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
            return f"已结束任务：{finished}；已准备 {candidate_count} 条长期候选。"
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

        self._project_context_files = self._load_project_context(self._project_identity)
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

    def begin_user_turn(self, user_message: str) -> None:
        """在压缩后的 transcript 上固定本轮 Overlay 并启动召回预取。"""

        if not self._is_sub_agent:
            self._reload_session_memory()
            self._report_session_memory_error()
            self._memory_coordinator.collect_ready()
            self._memory_coordinator.begin_turn(user_message)
        self._turn_memory_overlays = self._build_turn_memory_overlays()

    def project(
        self,
        messages: Sequence[AgentMessage],
        *,
        max_tokens: int | None,
    ) -> list[AgentMessage]:
        """把本轮 Memory 非破坏性地叠加到 Provider 投影。"""

        projected, report = self._memory_injector.inject(
            tuple(messages),
            self._turn_memory_overlays,
            max_tokens=max_tokens,
        )
        self._last_memory_injection = report
        return projected

    def reset_for_session(self) -> None:
        """清空旧会话运行态并重载项目、Session Memory。"""

        self._memory_coordinator.reset()
        self._reload_project_memory()
        self._reload_session_memory()
        self._reported_session_memory_error = None
        self._last_memory_injection = MemoryInjectionReport()
        self._turn_memory_overlays = self._build_turn_memory_overlays()

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
        self._notices.emit(f"Session Memory unavailable: {error}", role="error")

    async def finish_user_turn(
        self,
        user_message: str,
        turn_start_index: int,
    ) -> None:
        """保存本轮工具事实与受限语义 patch，并刷新下一轮 Overlay。"""

        if self._cancellation.cancelled:
            self._memory_coordinator.cancel_pending()
        if not self._is_sub_agent and self._session_memory is not None:
            messages = self._transcript.messages[turn_start_index:]
            if messages and self._session_memory_error is None:
                memory = apply_tool_evidence(
                    self._session_memory,
                    extract_tool_evidence(messages),
                )
                if not self._cancellation.cancelled:
                    try:
                        patch = await self._extract_session_memory_semantics(
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
        self._turn_memory_overlays = self._build_turn_memory_overlays()

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
        query = self._query
        if query is None:
            return {}
        raw = await query.complete(
            system=SESSION_MEMORY_EXTRACTION_SYSTEM,
            user=json.dumps(payload, ensure_ascii=False),
            max_output_tokens=512,
        )
        return _parse_session_memory_patch(raw)

    async def close(self) -> None:
        """关闭 Memory 预取，避免退出时留下异步任务。"""

        await self._memory_coordinator.close()
