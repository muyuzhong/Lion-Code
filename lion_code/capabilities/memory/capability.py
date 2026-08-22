"""Memory Capability：把 ``MemoryStore`` 绑定为治理工具面。

工具契约（设计文档 7.1 节）：remember/manage 是 mutation，标记
``requires_confirmation`` 走 ToolRuntime 的 Permission 确认路径；
recall/review 只读。本 PR 不贡献 ContextLayer/PromptLayer（自动召回
属 PR4），MemoryStore 保持 Capability 私有。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ...context.estimator import estimate_text_tokens
from ...tooling.context import ToolContext
from ...tooling.types import JSONValue, LionTool, ToolCapabilities, ToolResult
from ..types import CapabilitySpec
from .store import (
    DEFAULT_REVIEW_OLDER_THAN_DAYS,
    DEFAULT_TOKEN_BUDGET,
    DEFAULT_TOP_K,
    MANAGE_ACTIONS,
    MemoryEntry,
    MemoryStore,
    MemoryStoreError,
    ReviewStaleCandidate,
)

_TYPE = "object"
_STR = "string"


class _ToolArgumentError(ValueError):
    """工具参数类型/取值不合法。"""


def _required_str(arguments: Mapping[str, JSONValue], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise _ToolArgumentError(f"argument '{name}' must be a non-empty string")
    return value


def _optional_str(
    arguments: Mapping[str, JSONValue],
    name: str,
) -> str | None:
    if name not in arguments or arguments[name] is None:
        return None
    return _required_str(arguments, name)


def _enum_str(
    arguments: Mapping[str, JSONValue],
    name: str,
    allowed: tuple[str, ...],
    default: str,
) -> str:
    if name not in arguments or arguments[name] is None:
        value = default
    else:
        value = _required_str(arguments, name)
    if value not in allowed:
        raise _ToolArgumentError(
            f"argument '{name}' must be one of {list(allowed)}, got: {value}"
        )
    return value


def _bool_arg(
    arguments: Mapping[str, JSONValue],
    name: str,
    default: bool = False,
) -> bool:
    value = arguments.get(name, default)
    if not isinstance(value, bool):
        raise _ToolArgumentError(f"argument '{name}' must be a boolean")
    return value


def _int_arg(arguments: Mapping[str, JSONValue], name: str, *, minimum: int) -> int:
    value = arguments.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise _ToolArgumentError(f"argument '{name}' must be an integer >= {minimum}")
    return value


def _str_list(arguments: Mapping[str, JSONValue], name: str) -> tuple[str, ...]:
    value = arguments.get(name, [])
    if not isinstance(value, list):
        raise _ToolArgumentError(
            f"argument '{name}' must be a list of non-empty strings"
        )
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise _ToolArgumentError(
                f"argument '{name}' must be a list of non-empty strings"
            )
        items.append(item)
    return tuple(items)


def _entry_json(entry: MemoryEntry) -> dict[str, JSONValue]:
    return {
        "id": entry.id,
        "scope": entry.scope,
        "kind": entry.kind,
        "stable_key": entry.stable_key,
        "content": entry.content,
        "trigger": entry.trigger,
        "recall_mode": entry.recall_mode,
        "status": entry.status,
        "evidence": list(entry.evidence),
        "paths": list(entry.paths),
        "source_session_id": entry.source_session_id,
        "created_at": entry.created_at,
        "validated_at": entry.validated_at,
        "supersedes_id": entry.supersedes_id,
    }


def _candidate_json(candidate: ReviewStaleCandidate) -> dict[str, JSONValue]:
    return {
        "id": candidate.entry_id,
        "stable_key": candidate.stable_key,
        "missing_paths": list(candidate.missing_paths),
    }


def _entry_line(entry: MemoryEntry) -> str:
    """按设计 6.3 的行形状渲染：id + 象限 + 内容 + evidence。"""
    if entry.kind == "behavior":
        # behavior 的 trigger 非空由 schema CHECK 保证
        body = f"When: {entry.trigger} Do: {entry.content}"
    else:
        body = entry.content
    suffix = f" Evidence: {'; '.join(entry.evidence)}"
    if entry.paths:
        suffix += f" Paths: {', '.join(entry.paths)}"
    if entry.status != "active":
        suffix += f" [{entry.status}]"
    return f"- [m:{entry.id} {entry.display_path()}] {entry.stable_key}: {body}{suffix}"


def _error(exc: Exception) -> ToolResult:
    return ToolResult(content=f"memory error: {exc}", is_error=True)


class _MemoryToolSource:
    """提供绑定同一个 ``MemoryStore`` 的五个治理工具。"""

    def __init__(self, store: MemoryStore, *, project_root: Path | None) -> None:
        self._store = store
        self._project_root = project_root
        self._tools: tuple[LionTool, ...] = (
            self._recall_tool(),
            self._remember_definition_tool(),
            self._remember_behavior_tool(),
            self._review_tool(),
            self._manage_tool(),
        )

    def tools(self) -> tuple[LionTool, ...]:
        return self._tools

    # ------------------------------------------------------------------
    # recall_memory（只读）
    # ------------------------------------------------------------------

    def _recall_tool(self) -> LionTool:
        async def execute(
            context: ToolContext,
            tool_call_id: str,
            arguments: Mapping[str, JSONValue],
            on_update: object,
        ) -> ToolResult:
            del context, tool_call_id, on_update
            try:
                query = _required_str(arguments, "query")
                paths = _str_list(arguments, "paths")
                include_inactive = _bool_arg(arguments, "include_inactive")
                combined = " ".join((query, *paths))
                hits = self._store.search(
                    combined,
                    include_inactive=include_inactive,
                    top_k=DEFAULT_TOP_K,
                )
                entries = [hit.entry for hit in hits]
                entries, candidates = MemoryStore.partition_by_path_health(
                    entries, self._project_root
                )
                return self._render_recall(query, entries, candidates)
            except (_ToolArgumentError, MemoryStoreError) as exc:
                return _error(exc)

        return LionTool(
            name="recall_memory",
            label="Recall memory",
            description=(
                "Search semantic memory (definitions and behaviors) for the "
                "current user and project. Returns matching entries with "
                "evidence so they can be verified against current source. "
                "Memory is historical context: current instructions, AGENTS, "
                "source and tests always win."
            ),
            parameters={
                "type": _TYPE,
                "properties": {
                    "query": {
                        "type": _STR,
                        "description": "Search terms, stable keys or file paths",
                    },
                    "paths": {
                        "type": "array",
                        "items": {"type": _STR},
                        "description": "Optional project paths to include in search",
                    },
                    "include_inactive": {
                        "type": "boolean",
                        "description": "Also return stale entries (default false)",
                    },
                },
                "required": ["query"],
            },
            execute_fn=execute,
            capabilities=ToolCapabilities(
                read_only=True,
                concurrency_safe=True,
            ),
            execution_mode="parallel",
        )

    def _render_recall(
        self,
        query: str,
        entries: list[MemoryEntry],
        candidates: list[ReviewStaleCandidate],
    ) -> ToolResult:
        used = 0
        kept: list[MemoryEntry] = []
        truncated = False
        for index, entry in enumerate(entries):
            cost = estimate_text_tokens(_entry_line(entry))
            if index and used + cost > DEFAULT_TOKEN_BUDGET:
                truncated = True
                break
            used += cost
            kept.append(entry)
        lines = [f"Found {len(kept)} memory entries for: {query}"]
        lines.extend(_entry_line(entry) for entry in kept)
        if truncated:
            lines.append(
                f"(result truncated to fit {DEFAULT_TOKEN_BUDGET}-token budget)"
            )
        if candidates:
            lines.append(
                "Stale candidates (all paths missing; verify then "
                "manage_memory mark_stale):"
            )
            lines.extend(
                f"- m:{candidate.entry_id} {candidate.stable_key} "
                f"(missing: {', '.join(candidate.missing_paths)})"
                for candidate in candidates
            )
        return ToolResult(
            content="\n".join(lines),
            details={
                "entries": [_entry_json(entry) for entry in kept],
                "stale_candidates": [
                    _candidate_json(candidate) for candidate in candidates
                ],
                "truncated": truncated,
                "token_budget": DEFAULT_TOKEN_BUDGET,
            },
        )

    # ------------------------------------------------------------------
    # remember_definition / remember_behavior（mutation）
    # ------------------------------------------------------------------

    def _remember_definition_tool(self) -> LionTool:
        async def execute(
            context: ToolContext,
            tool_call_id: str,
            arguments: Mapping[str, JSONValue],
            on_update: object,
        ) -> ToolResult:
            del tool_call_id, on_update
            try:
                entry = self._store.remember(
                    kind="definition",
                    scope=_enum_str(
                        arguments, "scope", ("long_term", "project"), "project"
                    ),
                    stable_key=_required_str(arguments, "stable_key"),
                    content=_required_str(arguments, "content"),
                    evidence=_str_list(arguments, "evidence"),
                    paths=_str_list(arguments, "paths"),
                    recall_mode=_enum_str(
                        arguments, "recall_mode", ("pinned", "relevant"), "relevant"
                    ),
                    source_session_id=context.session.id,
                )
                return _render_remembered(entry)
            except (_ToolArgumentError, MemoryStoreError) as exc:
                return _error(exc)

        return LionTool(
            name="remember_definition",
            label="Remember definition",
            description=(
                "Store a durable definition (what something is) in semantic "
                "memory. Re-remembering the same stable_key creates a new "
                "revision and archives the old one. Only store facts the user "
                "asked to keep or that were verified against source/tests."
            ),
            parameters={
                "type": _TYPE,
                "properties": {
                    "scope": {
                        "type": _STR,
                        "enum": ["long_term", "project"],
                        "description": "project defaults to the current project",
                    },
                    "stable_key": {
                        "type": _STR,
                        "description": "Readable identity key unique per quadrant",
                    },
                    "content": {
                        "type": _STR,
                        "description": "The definition statement",
                    },
                    "evidence": {
                        "type": "array",
                        "items": {"type": _STR},
                        "description": "How to re-verify (files, commands, session)",
                    },
                    "paths": {
                        "type": "array",
                        "items": {"type": _STR},
                        "description": "Project-relative paths (project scope only)",
                    },
                    "recall_mode": {
                        "type": _STR,
                        "enum": ["pinned", "relevant"],
                        "description": (
                            "pinned entries surface every turn (default relevant)"
                        ),
                    },
                },
                "required": ["stable_key", "content", "evidence"],
            },
            execute_fn=execute,
            capabilities=ToolCapabilities(
                requires_confirmation=True,
            ),
        )

    def _remember_behavior_tool(self) -> LionTool:
        async def execute(
            context: ToolContext,
            tool_call_id: str,
            arguments: Mapping[str, JSONValue],
            on_update: object,
        ) -> ToolResult:
            del tool_call_id, on_update
            try:
                entry = self._store.remember(
                    kind="behavior",
                    scope=_enum_str(
                        arguments, "scope", ("long_term", "project"), "project"
                    ),
                    stable_key=_required_str(arguments, "stable_key"),
                    content=_required_str(arguments, "instruction"),
                    evidence=_str_list(arguments, "evidence"),
                    trigger=_required_str(arguments, "trigger"),
                    paths=_str_list(arguments, "paths"),
                    recall_mode=_enum_str(
                        arguments, "recall_mode", ("pinned", "relevant"), "relevant"
                    ),
                    source_session_id=context.session.id,
                )
                return _render_remembered(entry)
            except (_ToolArgumentError, MemoryStoreError) as exc:
                return _error(exc)

        return LionTool(
            name="remember_behavior",
            label="Remember behavior",
            description=(
                "Store a durable behavior (when to do what) in semantic memory. "
                "trigger describes when it applies; instruction what to do. "
                "Re-remembering the same stable_key supersedes the old revision."
            ),
            parameters={
                "type": _TYPE,
                "properties": {
                    "scope": {
                        "type": _STR,
                        "enum": ["long_term", "project"],
                        "description": "project defaults to the current project",
                    },
                    "stable_key": {
                        "type": _STR,
                        "description": "Readable identity key unique per quadrant",
                    },
                    "trigger": {
                        "type": _STR,
                        "description": "When this behavior applies",
                    },
                    "instruction": {
                        "type": _STR,
                        "description": "What to do when it applies",
                    },
                    "evidence": {
                        "type": "array",
                        "items": {"type": _STR},
                        "description": "How to re-verify (files, commands, session)",
                    },
                    "paths": {
                        "type": "array",
                        "items": {"type": _STR},
                        "description": "Project-relative paths (project scope only)",
                    },
                    "recall_mode": {
                        "type": _STR,
                        "enum": ["pinned", "relevant"],
                        "description": (
                            "pinned entries surface every turn (default relevant)"
                        ),
                    },
                },
                "required": ["stable_key", "trigger", "instruction", "evidence"],
            },
            execute_fn=execute,
            capabilities=ToolCapabilities(
                requires_confirmation=True,
            ),
        )

    # ------------------------------------------------------------------
    # review_memory（只读）
    # ------------------------------------------------------------------

    def _review_tool(self) -> LionTool:
        async def execute(
            context: ToolContext,
            tool_call_id: str,
            arguments: Mapping[str, JSONValue],
            on_update: object,
        ) -> ToolResult:
            del context, tool_call_id, on_update
            try:
                report = self._store.review(
                    _enum_str(
                        arguments, "scope", ("all", "long_term", "project"), "all"
                    ),
                    older_than_days=_int_arg(arguments, "older_than_days", minimum=0)
                    if "older_than_days" in arguments
                    else DEFAULT_REVIEW_OLDER_THAN_DAYS,
                    project_root=self._project_root,
                )
            except (_ToolArgumentError, MemoryStoreError) as exc:
                return _error(exc)
            lines = [
                "Memory review",
                f"- stale: {len(report.stale)}",
                f"- stale candidates (paths missing): {len(report.stale_candidates)}",
                "- long unvalidated "
                f"(>{report.older_than_days}d): {len(report.long_unvalidated)}",
                f"- pinned tokens: {report.pinned_tokens}"
                f"/{report.pinned_token_budget}"
                + (" (OVERFLOW)" if report.pinned_overflow else ""),
                f"- revision chains: {len(report.revision_chains)}",
                f"- archived revisions: {report.archived_count}",
            ]
            lines.extend(
                f"stale m:{entry.id} {entry.stable_key}: {entry.archived_reason}"
                for entry in report.stale
            )
            lines.extend(
                f"stale-candidate m:{candidate.entry_id} "
                f"{candidate.stable_key} "
                f"(missing: {', '.join(candidate.missing_paths)})"
                for candidate in report.stale_candidates
            )
            lines.extend(
                f"unvalidated m:{entry.id} {entry.stable_key}"
                for entry in report.long_unvalidated
            )
            lines.extend(
                f"pinned m:{entry.id} {entry.stable_key}"
                for entry in report.pinned_overflow
            )
            return ToolResult(
                content="\n".join(lines),
                details={
                    "scope": report.scope,
                    "stale": [_entry_json(entry) for entry in report.stale],
                    "stale_candidates": [
                        _candidate_json(candidate)
                        for candidate in report.stale_candidates
                    ],
                    "long_unvalidated": [
                        _entry_json(entry) for entry in report.long_unvalidated
                    ],
                    "revision_chains": [
                        {
                            "active_id": chain.active_id,
                            "stable_key": chain.stable_key,
                            "superseded_ids": list(chain.superseded_ids),
                        }
                        for chain in report.revision_chains
                    ],
                },
            )

        return LionTool(
            name="review_memory",
            label="Review memory",
            description=(
                "Review memory health: stale entries, entries whose paths no "
                "longer exist, long-unvalidated entries, pinned token "
                "overflow, and revision chains."
            ),
            parameters={
                "type": _TYPE,
                "properties": {
                    "scope": {
                        "type": _STR,
                        "enum": ["all", "long_term", "project"],
                        "description": "Which scope to review (default all)",
                    },
                    "older_than_days": {
                        "type": "integer",
                        "description": (
                            "Unvalidated threshold in days (default "
                            f"{DEFAULT_REVIEW_OLDER_THAN_DAYS})"
                        ),
                    },
                },
            },
            execute_fn=execute,
            capabilities=ToolCapabilities(
                read_only=True,
                concurrency_safe=True,
            ),
            execution_mode="parallel",
        )

    # ------------------------------------------------------------------
    # manage_memory（mutation）
    # ------------------------------------------------------------------

    def _manage_tool(self) -> LionTool:
        async def execute(
            context: ToolContext,
            tool_call_id: str,
            arguments: Mapping[str, JSONValue],
            on_update: object,
        ) -> ToolResult:
            del context, tool_call_id, on_update
            entry_id = 0
            action = ""
            try:
                entry_id = _int_arg(arguments, "id", minimum=1)
                action = _required_str(arguments, "action")
                if action not in MANAGE_ACTIONS:
                    raise _ToolArgumentError(
                        f"argument 'action' must be one of "
                        f"{list(MANAGE_ACTIONS)}, got: {action}"
                    )
                updated = self._store.manage(
                    entry_id,
                    action,
                    reason=_optional_str(arguments, "reason"),
                )
            except (_ToolArgumentError, MemoryStoreError) as exc:
                return _error(exc)
            if updated is None:
                return ToolResult(
                    content=(
                        f"purged m:{entry_id} "
                        "(physically deleted; this cannot be undone)"
                    ),
                    details={"id": entry_id, "action": action},
                )
            status_note = (
                f" ({updated.archived_reason})" if updated.archived_reason else ""
            )
            return ToolResult(
                content=(
                    f"{action} m:{updated.id} {updated.stable_key} -> "
                    f"{updated.status}{status_note}"
                ),
                details={"entry": _entry_json(updated), "action": action},
            )

        return LionTool(
            name="manage_memory",
            label="Manage memory",
            description=(
                "Manage a memory entry lifecycle: mark_stale, archive "
                "(recoverable), restore, validate (refresh validation time), "
                "or purge (permanent physical deletion). mark_stale, archive "
                "and purge require a reason."
            ),
            parameters={
                "type": _TYPE,
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "Memory entry id (m:<id> from recall/review)",
                    },
                    "action": {
                        "type": _STR,
                        "enum": list(MANAGE_ACTIONS),
                        "description": "Lifecycle action to apply",
                    },
                    "reason": {
                        "type": _STR,
                        "description": "Required for mark_stale, archive and purge",
                    },
                },
                "required": ["id", "action"],
            },
            execute_fn=execute,
            capabilities=ToolCapabilities(
                requires_confirmation=True,
            ),
        )


def _render_remembered(entry: MemoryEntry) -> ToolResult:
    superseded = (
        f" (superseded revision m:{entry.supersedes_id})"
        if entry.supersedes_id is not None
        else ""
    )
    return ToolResult(
        content=(
            f"remembered m:{entry.id} [{entry.display_path()}] "
            f"{entry.stable_key}{superseded}"
        ),
        details={"entry": _entry_json(entry)},
    )


def create_memory_capability(
    store: MemoryStore,
    *,
    project_root: Path | None = None,
) -> CapabilitySpec:
    """返回提供 memory 治理工具的 Capability。

    ``project_root`` 用于命中条目的确定性 path 存在性校验；为 None 时
    跳过校验（不产生 stale candidate）。
    """
    return CapabilitySpec(
        name="memory",
        tool_sources=(_MemoryToolSource(store, project_root=project_root),),
    )
