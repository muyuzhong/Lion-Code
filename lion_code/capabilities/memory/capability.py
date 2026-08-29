"""显式 Memory 工具与静态 MemoryPolicy PromptLayer。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ...context.estimator import APPROXIMATE_CHARS_PER_TOKEN, estimate_text_tokens
from ...context.projector import budget_text
from ...context.types import ContextView
from ...tooling.context import ToolContext
from ...tooling.types import JSONValue, LionTool, ToolCapabilities, ToolResult
from ..types import CapabilitySpec
from .rendering import entry_line, render_pinned, select_pinned, task_line
from .store import (
    EVIDENCE_TYPES,
    MAX_MEMORY_RESULTS,
    MemoryEntry,
    MemoryStore,
    MemoryStoreError,
    ReviewEntry,
    TaskEntry,
)

_TYPE = "object"
_STRING = "string"
_RECALL_TOKEN_BUDGET = 800
_READ_ONLY = ToolCapabilities(read_only=True, concurrency_safe=True)


class _ToolArgumentError(ValueError):
    pass


def _required_str(arguments: Mapping[str, JSONValue], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise _ToolArgumentError(f"argument '{name}' must be a non-empty string")
    return value


def _optional_str(arguments: Mapping[str, JSONValue], name: str) -> str | None:
    value = arguments.get(name)
    if value is None:
        return None
    return _required_str(arguments, name)


def _enum(
    arguments: Mapping[str, JSONValue],
    name: str,
    allowed: tuple[str, ...],
    *,
    default: str,
) -> str:
    value = _optional_str(arguments, name) or default
    if value not in allowed:
        raise _ToolArgumentError(
            f"argument '{name}' must be one of {list(allowed)}, got: {value}"
        )
    return value


def _positive_int(arguments: Mapping[str, JSONValue], name: str) -> int:
    value = arguments.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise _ToolArgumentError(f"argument '{name}' must be an integer >= 1")
    return value


def _bool(arguments: Mapping[str, JSONValue], name: str) -> bool:
    value = arguments.get(name)
    if not isinstance(value, bool):
        raise _ToolArgumentError(f"argument '{name}' must be a boolean")
    return value


def _strings(arguments: Mapping[str, JSONValue], name: str) -> tuple[str, ...]:
    value = arguments.get(name, [])
    if not isinstance(value, list):
        raise _ToolArgumentError(f"argument '{name}' must be a string list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise _ToolArgumentError(f"argument '{name}' must be a string list")
        result.append(item)
    return tuple(result)


def _error(exc: Exception) -> ToolResult:
    return ToolResult(content=f"memory error: {exc}", is_error=True)


def _memory_json(entry: MemoryEntry) -> dict[str, JSONValue]:
    return {
        "id": entry.id,
        "scope": entry.scope,
        "project_key": entry.project_key,
        "kind": entry.kind,
        "stable_key": entry.stable_key,
        "content": entry.content,
        "trigger": entry.trigger,
        "pinned": entry.pinned,
        "evidence_type": entry.evidence_type,
        "evidence_ref": entry.evidence_ref,
        "paths": list(entry.paths),
        "validated_at": entry.validated_at,
        "archived_at": entry.archived_at,
    }


def _task_json(task: TaskEntry) -> dict[str, JSONValue]:
    return {
        "id": task.id,
        "project_key": task.project_key,
        "stable_key": task.stable_key,
        "title": task.title,
        "objective": task.objective,
        "summary": task.summary,
        "next_action": task.next_action,
        "status": task.status,
        "refs": list(task.refs),
        "archived_at": task.archived_at,
    }


def _schema(
    properties: dict[str, JSONValue], required: tuple[str, ...] = ()
) -> dict[str, JSONValue]:
    schema: dict[str, JSONValue] = {"type": _TYPE, "properties": properties}
    if required:
        schema["required"] = list(required)
    return schema


def _evidence_properties() -> dict[str, JSONValue]:
    return {
        "evidence_type": {"type": _STRING, "enum": list(EVIDENCE_TYPES)},
        "evidence_ref": {
            "type": _STRING,
            "description": "Non-empty reference that can be checked again",
        },
    }


class MemoryPolicyPromptLayer:
    """约束任务与语义记忆维护时机的静态策略。"""

    layer_id = "memory-policy"

    def render(self) -> str:
        return """# Memory Policy

- When the user asks to continue work or list unfinished work, call recall_tasks; do not infer the task from old sessions.
- Update a task only when it is created, its objective or next action changes, a significant milestone is reached, or it is completed or reopened.
- Store semantic memory only when it remains useful across sessions, cannot be cheaply reconstructed from an authoritative source, and has typed evidence; never store secrets, guesses, transient state, or repository maps.
- Current user instructions, AGENTS, current source, tests, and Git evidence always override Memory."""


class _PinnedMemoryContextLayer:
    """把已复核的 pinned 语义记忆投影到单次 prepared context。"""

    layer_id = "memory"

    def __init__(self, store: MemoryStore, *, project_root: Path | None) -> None:
        self._store = store
        self._project_root = project_root

    def render(self, view: ContextView) -> str:
        del view
        selection = select_pinned(self._store.pinned(project_root=self._project_root))
        return render_pinned(selection.entries)


class _MemoryToolSource:
    def __init__(self, store: MemoryStore, *, project_root: Path | None) -> None:
        self._store = store
        self._project_root = project_root
        self._tools = (
            self._remember_task_tool(),
            self._recall_tasks_tool(),
            self._remember_semantic_tool("definition"),
            self._remember_semantic_tool("behavior"),
            self._recall_memory_tool(),
            self._review_tool(),
            self._manage_tool(),
            self._set_pinned_tool(),
            self._purge_tool(),
        )

    def tools(self) -> tuple[LionTool, ...]:
        return self._tools

    def _remember_task_tool(self) -> LionTool:
        async def execute(
            context: ToolContext,
            tool_call_id: str,
            arguments: Mapping[str, JSONValue],
            on_update: object,
        ) -> ToolResult:
            del context, tool_call_id, on_update
            try:
                task = self._store.remember_task(
                    stable_key=_required_str(arguments, "stable_key"),
                    title=_required_str(arguments, "title"),
                    objective=_required_str(arguments, "objective"),
                    summary=_required_str(arguments, "summary"),
                    next_action=_required_str(arguments, "next_action"),
                    refs=_strings(arguments, "refs"),
                )
            except (_ToolArgumentError, MemoryStoreError) as exc:
                return _error(exc)
            return ToolResult(
                content=f"remembered task t:{task.id} {task.stable_key}",
                details={"task": _task_json(task)},
            )

        properties: dict[str, JSONValue] = {
            name: {"type": _STRING}
            for name in ("stable_key", "title", "objective", "summary", "next_action")
        }
        properties["refs"] = {"type": "array", "items": {"type": _STRING}}
        return LionTool(
            name="remember_task",
            description="Create or update one current-project task at a significant milestone.",
            parameters=_schema(
                properties,
                ("stable_key", "title", "objective", "summary", "next_action"),
            ),
            execute_fn=execute,
        )

    def _recall_tasks_tool(self) -> LionTool:
        async def execute(
            context: ToolContext,
            tool_call_id: str,
            arguments: Mapping[str, JSONValue],
            on_update: object,
        ) -> ToolResult:
            del context, tool_call_id, on_update
            try:
                tasks = self._store.recall_tasks(
                    stable_key=_optional_str(arguments, "stable_key"),
                    status=_enum(
                        arguments,
                        "status",
                        ("open", "completed", "all"),
                        default="open",
                    ),
                )
            except (_ToolArgumentError, MemoryStoreError) as exc:
                return _error(exc)
            if not tasks:
                content = "No matching tasks in the current project."
            elif len(tasks) == 1:
                content = "One matching task:\n" + task_line(tasks[0], detailed=True)
            else:
                content = f"{len(tasks)} matching tasks; choose one:\n" + "\n".join(
                    task_line(task, detailed=False) for task in tasks
                )
            content = budget_text(
                content, _RECALL_TOKEN_BUDGET * APPROXIMATE_CHARS_PER_TOKEN
            )
            return ToolResult(
                content=content,
                details={"tasks": [_task_json(task) for task in tasks]},
            )

        return LionTool(
            name="recall_tasks",
            description="List bounded current-project tasks without reading old sessions.",
            parameters=_schema(
                {
                    "stable_key": {"type": _STRING},
                    "status": {
                        "type": _STRING,
                        "enum": ["open", "completed", "all"],
                    },
                }
            ),
            execute_fn=execute,
            capabilities=_READ_ONLY,
            execution_mode="parallel",
        )

    def _remember_semantic_tool(self, kind: str) -> LionTool:
        name = f"remember_{kind}"

        async def execute(
            context: ToolContext,
            tool_call_id: str,
            arguments: Mapping[str, JSONValue],
            on_update: object,
        ) -> ToolResult:
            del context, tool_call_id, on_update
            try:
                entry = self._store.remember(
                    kind=kind,
                    scope=_enum(
                        arguments,
                        "scope",
                        ("long_term", "project"),
                        default="project",
                    ),
                    stable_key=_required_str(arguments, "stable_key"),
                    content=_required_str(
                        arguments, "instruction" if kind == "behavior" else "content"
                    ),
                    trigger=(
                        _required_str(arguments, "trigger")
                        if kind == "behavior"
                        else None
                    ),
                    evidence_type=_enum(
                        arguments,
                        "evidence_type",
                        EVIDENCE_TYPES,
                        default="",
                    ),
                    evidence_ref=_required_str(arguments, "evidence_ref"),
                    paths=_strings(arguments, "paths"),
                )
            except (_ToolArgumentError, MemoryStoreError) as exc:
                return _error(exc)
            return ToolResult(
                content=f"remembered m:{entry.id} [{entry.display_path()}] {entry.stable_key}",
                details={"entry": _memory_json(entry)},
            )

        content_name = "instruction" if kind == "behavior" else "content"
        properties: dict[str, JSONValue] = {
            "scope": {"type": _STRING, "enum": ["long_term", "project"]},
            "stable_key": {"type": _STRING},
            content_name: {"type": _STRING},
            "paths": {"type": "array", "items": {"type": _STRING}},
            **_evidence_properties(),
        }
        required = ["stable_key", content_name, "evidence_type", "evidence_ref"]
        if kind == "behavior":
            properties["trigger"] = {"type": _STRING}
            required.insert(1, "trigger")
        return LionTool(
            name=name,
            description=(
                "Store a durable definition (what something is) with typed evidence."
                if kind == "definition"
                else "Store a durable behavior (when to do what) with typed evidence."
            ),
            parameters=_schema(properties, tuple(required)),
            execute_fn=execute,
        )

    def _recall_memory_tool(self) -> LionTool:
        async def execute(
            context: ToolContext,
            tool_call_id: str,
            arguments: Mapping[str, JSONValue],
            on_update: object,
        ) -> ToolResult:
            del context, tool_call_id, on_update
            try:
                query = _required_str(arguments, "query")
                entries = self._store.recall_memory(
                    query,
                    project_root=self._project_root,
                    limit=MAX_MEMORY_RESULTS,
                )
            except (_ToolArgumentError, MemoryStoreError) as exc:
                return _error(exc)
            kept: list[MemoryEntry] = []
            used = 0
            for entry in entries:
                cost = estimate_text_tokens(entry_line(entry))
                if used + cost > _RECALL_TOKEN_BUDGET:
                    continue
                kept.append(entry)
                used += cost
            content = (
                "No active, reviewed semantic memory matched the query."
                if not kept
                else f"Found {len(kept)} memory entries:\n"
                + "\n".join(entry_line(entry) for entry in kept)
            )
            return ToolResult(
                content=content,
                details={"entries": [_memory_json(entry) for entry in kept]},
            )

        return LionTool(
            name="recall_memory",
            description="Exact-key or bounded literal recall from reviewed active memory.",
            parameters=_schema({"query": {"type": _STRING}}, ("query",)),
            execute_fn=execute,
            capabilities=_READ_ONLY,
            execution_mode="parallel",
        )

    def _review_tool(self) -> LionTool:
        async def execute(
            context: ToolContext,
            tool_call_id: str,
            arguments: Mapping[str, JSONValue],
            on_update: object,
        ) -> ToolResult:
            del context, tool_call_id, on_update
            try:
                view = _enum(
                    arguments,
                    "view",
                    ("needs_review", "archived", "pinned_overflow"),
                    default="needs_review",
                )
                target = _enum(
                    arguments,
                    "target",
                    ("semantic", "task"),
                    default="semantic",
                )
                return self._render_review(view, target)
            except (_ToolArgumentError, MemoryStoreError) as exc:
                return _error(exc)

        return LionTool(
            name="review_memory",
            description="List bounded needs-review, archived, or pinned-overflow ids.",
            parameters=_schema(
                {
                    "view": {
                        "type": _STRING,
                        "enum": ["needs_review", "archived", "pinned_overflow"],
                    },
                    "target": {
                        "type": _STRING,
                        "enum": ["semantic", "task"],
                    },
                }
            ),
            execute_fn=execute,
            capabilities=_READ_ONLY,
            execution_mode="parallel",
        )

    def _render_review(self, view: str, target: str) -> ToolResult:
        if view == "needs_review":
            reviews = (
                self._store.needs_review(project_root=self._project_root)
                if target == "semantic"
                else []
            )
            return ToolResult(
                content=(
                    "No entries need review."
                    if not reviews
                    else "Needs review:\n"
                    + "\n".join(
                        f"- m:{item.entry.id} {item.entry.stable_key}: "
                        f"{'; '.join(item.reasons)}"
                        for item in reviews
                    )
                ),
                details={
                    "view": view,
                    "target": target,
                    "entries": [self._review_json(item) for item in reviews],
                },
            )
        if view == "archived":
            details: list[JSONValue]
            if target == "task":
                tasks = self._store.archived_tasks()
                content = "\n".join(task_line(task, detailed=False) for task in tasks)
                details = [_task_json(task) for task in tasks]
            else:
                entries = self._store.archived_semantic()
                content = "\n".join(entry_line(entry) for entry in entries)
                details = [_memory_json(entry) for entry in entries]
            return ToolResult(
                content=content or "No archived entries.",
                details={"view": view, "target": target, "entries": details},
            )
        if target == "task":
            return ToolResult(
                content="Tasks are not pinned.",
                details={"view": view, "target": target, "entries": []},
            )
        overflow = select_pinned(
            self._store.pinned(project_root=self._project_root)
        ).overflow
        return ToolResult(
            content=(
                "No pinned overflow."
                if not overflow
                else "Pinned overflow:\n"
                + "\n".join(f"- m:{entry.id} {entry.stable_key}" for entry in overflow)
            ),
            details={
                "view": view,
                "target": target,
                "entries": [_memory_json(entry) for entry in overflow],
            },
        )

    @staticmethod
    def _review_json(item: ReviewEntry) -> dict[str, JSONValue]:
        return {"entry": _memory_json(item.entry), "reasons": list(item.reasons)}

    def _manage_tool(self) -> LionTool:
        async def execute(
            context: ToolContext,
            tool_call_id: str,
            arguments: Mapping[str, JSONValue],
            on_update: object,
        ) -> ToolResult:
            del context, tool_call_id, on_update
            try:
                target = _enum(
                    arguments, "target", ("semantic", "task"), default="semantic"
                )
                entry_id = _positive_int(arguments, "id")
                action = _enum(
                    arguments,
                    "action",
                    ("archive", "restore", "validate", "complete", "reopen"),
                    default="",
                )
                if target == "semantic":
                    updated: MemoryEntry | TaskEntry
                    if action == "archive":
                        updated = self._store.archive_semantic(entry_id)
                    elif action == "restore":
                        updated = self._store.restore_semantic(entry_id)
                    elif action == "validate":
                        updated = self._store.validate_semantic(
                            entry_id,
                            evidence_type=_enum(
                                arguments,
                                "evidence_type",
                                EVIDENCE_TYPES,
                                default="",
                            ),
                            evidence_ref=_required_str(arguments, "evidence_ref"),
                        )
                    else:
                        raise _ToolArgumentError(
                            f"action '{action}' is not valid for semantic memory"
                        )
                    details: dict[str, JSONValue] = {"entry": _memory_json(updated)}
                else:
                    if action == "archive":
                        task = self._store.archive_task(entry_id)
                    elif action == "restore":
                        task = self._store.restore_task(entry_id)
                    elif action == "complete":
                        task = self._store.complete_task(entry_id)
                    elif action == "reopen":
                        task = self._store.reopen_task(entry_id)
                    else:
                        raise _ToolArgumentError(
                            f"action '{action}' is not valid for tasks"
                        )
                    details = {"task": _task_json(task)}
            except (_ToolArgumentError, MemoryStoreError) as exc:
                return _error(exc)
            return ToolResult(
                content=f"{action} {target} {entry_id}",
                details={"action": action, "target": target, **details},
            )

        properties: dict[str, JSONValue] = {
            "target": {"type": _STRING, "enum": ["semantic", "task"]},
            "id": {"type": "integer"},
            "action": {
                "type": _STRING,
                "enum": ["archive", "restore", "validate", "complete", "reopen"],
            },
            **_evidence_properties(),
        }
        return LionTool(
            name="manage_memory",
            description="Archive/restore/validate semantic memory or complete/reopen/archive/restore tasks.",
            parameters=_schema(properties, ("target", "id", "action")),
            execute_fn=execute,
        )

    def _set_pinned_tool(self) -> LionTool:
        async def execute(
            context: ToolContext,
            tool_call_id: str,
            arguments: Mapping[str, JSONValue],
            on_update: object,
        ) -> ToolResult:
            del context, tool_call_id, on_update
            try:
                entry = self._store.set_pinned(
                    _positive_int(arguments, "id"),
                    pinned=_bool(arguments, "pinned"),
                )
            except (_ToolArgumentError, MemoryStoreError) as exc:
                return _error(exc)
            return ToolResult(
                content=f"set m:{entry.id} pinned={entry.pinned}",
                details={"entry": _memory_json(entry)},
            )

        return LionTool(
            name="set_memory_pinned",
            description="Pin or unpin one semantic memory entry.",
            parameters=_schema(
                {"id": {"type": "integer"}, "pinned": {"type": "boolean"}},
                ("id", "pinned"),
            ),
            execute_fn=execute,
            capabilities=ToolCapabilities(requires_confirmation=True),
        )

    def _purge_tool(self) -> LionTool:
        async def execute(
            context: ToolContext,
            tool_call_id: str,
            arguments: Mapping[str, JSONValue],
            on_update: object,
        ) -> ToolResult:
            del context, tool_call_id, on_update
            try:
                target = _enum(
                    arguments, "target", ("semantic", "task"), default="semantic"
                )
                entry_id = _positive_int(arguments, "id")
                if target == "semantic":
                    self._store.purge_semantic(entry_id)
                else:
                    self._store.purge_task(entry_id)
            except (_ToolArgumentError, MemoryStoreError) as exc:
                return _error(exc)
            return ToolResult(
                content=f"purged {target} {entry_id}; this cannot be undone",
                details={"target": target, "id": entry_id},
            )

        return LionTool(
            name="purge_memory",
            description="Physically delete one task or semantic entry.",
            parameters=_schema(
                {
                    "target": {"type": _STRING, "enum": ["semantic", "task"]},
                    "id": {"type": "integer"},
                },
                ("target", "id"),
            ),
            execute_fn=execute,
            capabilities=ToolCapabilities(requires_confirmation=True),
        )


def create_memory_capability(
    store: MemoryStore,
    *,
    project_root: Path | None = None,
) -> CapabilitySpec:
    """把一个私有 store 绑定到显式工具和静态策略提示。"""
    return CapabilitySpec(
        name="memory",
        tool_sources=(_MemoryToolSource(store, project_root=project_root),),
        prompt_layers=(MemoryPolicyPromptLayer(),),
        context_layer=_PinnedMemoryContextLayer(
            store,
            project_root=project_root,
        ),
    )
