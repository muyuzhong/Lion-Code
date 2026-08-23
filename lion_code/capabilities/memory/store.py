"""Capability 私有的项目任务与语义记忆 SQLite 存储。"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath, PureWindowsPath
from time import monotonic, sleep
from typing import Literal

MemoryScope = Literal["long_term", "project"]
MemoryKind = Literal["definition", "behavior"]
EvidenceType = Literal["user_request", "source", "test", "command"]
TaskStatus = Literal["open", "completed"]

SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 5000
MEMORY_REVIEW_AFTER_DAYS = 90
MAX_MEMORY_RESULTS = 6
MAX_TASK_RESULTS = 8
MAX_REVIEW_RESULTS = 20
PINNED_MEMORY_TOKEN_BUDGET = 512
MAX_PINNED_ENTRIES = 8

SCOPES = ("long_term", "project")
KINDS = ("definition", "behavior")
EVIDENCE_TYPES = ("user_request", "source", "test", "command")

_SCHEMA_SQL = (
    """
    CREATE TABLE semantic_entries (
        id INTEGER PRIMARY KEY,
        scope TEXT NOT NULL CHECK (scope IN ('long_term', 'project')),
        project_key TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('definition', 'behavior')),
        stable_key TEXT NOT NULL CHECK (length(stable_key) > 0),
        content TEXT NOT NULL CHECK (length(trim(content)) > 0),
        trigger TEXT NOT NULL DEFAULT '',
        pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
        evidence_type TEXT NOT NULL CHECK (
            evidence_type IN ('user_request', 'source', 'test', 'command')
        ),
        evidence_ref TEXT NOT NULL CHECK (length(trim(evidence_ref)) > 0),
        paths_json TEXT NOT NULL DEFAULT '[]' CHECK (
            json_valid(paths_json) AND json_type(paths_json) = 'array'
        ),
        validated_at TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        archived_at TEXT,
        CHECK ((scope = 'project' AND length(project_key) > 0)
            OR (scope = 'long_term' AND project_key = '')),
        CHECK ((kind = 'behavior' AND length(trim(trigger)) > 0)
            OR (kind = 'definition' AND trigger = '')),
        CHECK (scope = 'project' OR paths_json = '[]')
    )
    """,
    """
    CREATE TABLE tasks (
        id INTEGER PRIMARY KEY,
        project_key TEXT NOT NULL CHECK (length(project_key) > 0),
        stable_key TEXT NOT NULL CHECK (length(stable_key) > 0),
        title TEXT NOT NULL CHECK (length(trim(title)) > 0),
        objective TEXT NOT NULL CHECK (length(trim(objective)) > 0),
        summary TEXT NOT NULL CHECK (length(trim(summary)) > 0),
        next_action TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open'
            CHECK (status IN ('open', 'completed')),
        refs_json TEXT NOT NULL DEFAULT '[]' CHECK (
            json_valid(refs_json) AND json_type(refs_json) = 'array'
        ),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        archived_at TEXT,
        CHECK (status = 'completed' OR length(trim(next_action)) > 0)
    )
    """,
    """
    CREATE UNIQUE INDEX semantic_active_stable_key
    ON semantic_entries (scope, project_key, kind, stable_key)
    WHERE archived_at IS NULL
    """,
    """
    CREATE UNIQUE INDEX task_active_stable_key
    ON tasks (project_key, stable_key)
    WHERE archived_at IS NULL
    """,
)
_EXPECTED_OBJECTS = frozenset(
    {
        "semantic_entries",
        "tasks",
        "semantic_active_stable_key",
        "task_active_stable_key",
    }
)
_EXPECTED_COLUMNS = {
    "semantic_entries": (
        "id",
        "scope",
        "project_key",
        "kind",
        "stable_key",
        "content",
        "trigger",
        "pinned",
        "evidence_type",
        "evidence_ref",
        "paths_json",
        "validated_at",
        "created_at",
        "updated_at",
        "archived_at",
    ),
    "tasks": (
        "id",
        "project_key",
        "stable_key",
        "title",
        "objective",
        "summary",
        "next_action",
        "status",
        "refs_json",
        "created_at",
        "updated_at",
        "archived_at",
    ),
}


class MemoryStoreError(Exception):
    """显式 Memory 操作的错误基类。"""


class MemorySchemaError(MemoryStoreError):
    """数据库无法打开，或不是当前唯一支持的 schema。"""


class MemoryValidationError(MemoryStoreError):
    """输入违反 canonical task 或 semantic memory 契约。"""


class MemoryConflictError(MemoryStoreError):
    """生命周期操作与当前持久状态冲突。"""


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    id: int
    scope: MemoryScope
    project_key: str
    kind: MemoryKind
    stable_key: str
    content: str
    trigger: str
    pinned: bool
    evidence_type: EvidenceType
    evidence_ref: str
    paths: tuple[str, ...]
    validated_at: str
    created_at: str
    updated_at: str
    archived_at: str | None

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    def display_path(self) -> str:
        owner = self.project_key if self.scope == "project" else "long_term"
        return f"{owner}/{self.kind}"


@dataclass(frozen=True, slots=True)
class TaskEntry:
    id: int
    project_key: str
    stable_key: str
    title: str
    objective: str
    summary: str
    next_action: str
    status: TaskStatus
    refs: tuple[str, ...]
    created_at: str
    updated_at: str
    archived_at: str | None

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None


@dataclass(frozen=True, slots=True)
class ReviewEntry:
    entry: MemoryEntry
    reasons: tuple[str, ...]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _required_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MemoryValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _stable_key(value: str) -> str:
    return " ".join(_required_text(value, "stable_key").split()).casefold()


def _literal(value: str) -> str:
    return " ".join(value.replace("\\", "/").split()).casefold()


def _string_list(values: Sequence[str], field: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise MemoryValidationError(f"{field} must be a string list")
    result: list[str] = []
    for value in values:
        item = _required_text(value, field)
        if item not in result:
            result.append(item)
    return tuple(result)


def _paths(values: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in _string_list(values, "paths"):
        candidate = raw.replace("\\", "/")
        posix = PurePosixPath(candidate)
        windows = PureWindowsPath(raw)
        if (
            posix.is_absolute()
            or windows.is_absolute()
            or windows.drive
            or ".." in posix.parts
        ):
            raise MemoryValidationError(
                f"path must be project-relative without traversal: {raw}"
            )
        value = posix.as_posix()
        if value in ("", "."):
            raise MemoryValidationError("paths must contain project-relative paths")
        if value not in normalized:
            normalized.append(value)
    return tuple(normalized)


def _decode_strings(raw: str, field: str) -> tuple[str, ...]:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise MemorySchemaError(f"invalid {field} JSON in memory database") from exc
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise MemorySchemaError(f"invalid {field} value in memory database")
    return tuple(value)


def _memory_entry(row: sqlite3.Row) -> MemoryEntry:
    return MemoryEntry(
        id=int(row["id"]),
        scope=row["scope"],
        project_key=str(row["project_key"]),
        kind=row["kind"],
        stable_key=str(row["stable_key"]),
        content=str(row["content"]),
        trigger=str(row["trigger"]),
        pinned=bool(row["pinned"]),
        evidence_type=row["evidence_type"],
        evidence_ref=str(row["evidence_ref"]),
        paths=_decode_strings(row["paths_json"], "paths"),
        validated_at=str(row["validated_at"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        archived_at=row["archived_at"],
    )


def _task_entry(row: sqlite3.Row) -> TaskEntry:
    return TaskEntry(
        id=int(row["id"]),
        project_key=str(row["project_key"]),
        stable_key=str(row["stable_key"]),
        title=str(row["title"]),
        objective=str(row["objective"]),
        summary=str(row["summary"]),
        next_action=str(row["next_action"]),
        status=row["status"],
        refs=_decode_strings(row["refs_json"], "refs"),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        archived_at=row["archived_at"],
    )


class MemoryStore:
    """面向当前项目、延迟开库且每次操作使用独立连接的存储。"""

    def __init__(self, db_path: Path, *, project_key: str) -> None:
        self._db_path = Path(db_path)
        self._project_key = _required_text(project_key, "project_key")

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def project_key(self) -> str:
        return self._project_key

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                self._db_path,
                timeout=BUSY_TIMEOUT_MS / 1000,
                isolation_level=None,
            )
        except (OSError, sqlite3.Error) as exc:
            raise MemorySchemaError(
                f"cannot open memory database {self._db_path}: {exc}"
            ) from exc
        try:
            conn.row_factory = sqlite3.Row
            conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
            conn.execute("PRAGMA foreign_keys = ON")
            self._ensure_schema(conn)
        except MemoryStoreError:
            conn.close()
            raise
        except sqlite3.Error as exc:
            conn.close()
            raise MemorySchemaError(
                f"memory database {self._db_path} failed validation: {exc}"
            ) from exc
        try:
            yield conn
        except MemoryStoreError:
            raise
        except sqlite3.IntegrityError as exc:
            raise MemoryConflictError(
                f"memory database {self._db_path} constraint failed: {exc}"
            ) from exc
        except sqlite3.Error as exc:
            raise MemoryStoreError(
                f"memory database {self._db_path} operation failed: {exc}"
            ) from exc
        finally:
            conn.close()

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        version, objects = self._schema_snapshot(conn)
        if version == 0 and not objects:
            try:
                conn.execute("BEGIN IMMEDIATE")
                version, objects = self._schema_snapshot(conn)
                if version == 0 and not objects:
                    for statement in _SCHEMA_SQL:
                        conn.execute(statement)
                    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                conn.execute("COMMIT")
            except BaseException:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                raise
        self._verify_schema(conn)
        self._ensure_wal(conn)

    def _ensure_wal(self, conn: sqlite3.Connection) -> None:
        deadline = monotonic() + BUSY_TIMEOUT_MS / 1000
        while True:
            try:
                journal = conn.execute("PRAGMA journal_mode").fetchone()
                if journal is not None and str(journal[0]).casefold() == "wal":
                    return
                changed = conn.execute("PRAGMA journal_mode = WAL").fetchone()
                if changed is not None and str(changed[0]).casefold() == "wal":
                    return
                raise MemorySchemaError(
                    f"memory database {self._db_path} could not enable WAL mode"
                )
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).casefold() or monotonic() >= deadline:
                    raise
                sleep(0.05)

    @staticmethod
    def _schema_snapshot(conn: sqlite3.Connection) -> tuple[int, set[str]]:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' AND type IN ('table', 'index', 'view', 'trigger')"
        ).fetchall()
        return version, {str(row[0]) for row in rows}

    def _verify_schema(self, conn: sqlite3.Connection) -> None:
        version, objects = self._schema_snapshot(conn)
        if version != SCHEMA_VERSION:
            raise MemorySchemaError(
                f"memory database {self._db_path} schema version mismatch: expected "
                f"{SCHEMA_VERSION}, found {version}"
            )
        if objects != _EXPECTED_OBJECTS:
            missing = sorted(_EXPECTED_OBJECTS - objects)
            unexpected = sorted(objects - _EXPECTED_OBJECTS)
            raise MemorySchemaError(
                f"memory database {self._db_path} schema objects mismatch: "
                f"missing={missing}, unexpected={unexpected}"
            )
        for table, expected in _EXPECTED_COLUMNS.items():
            columns = tuple(
                str(row[1])
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            )
            if columns != expected:
                raise MemorySchemaError(
                    f"memory database {self._db_path} schema columns mismatch "
                    f"for {table}: expected={list(expected)}, found={list(columns)}"
                )
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or str(integrity[0]) != "ok":
            detail = integrity[0] if integrity is not None else "no result"
            raise MemorySchemaError(
                f"memory database {self._db_path} integrity check failed: {detail}"
            )

    @staticmethod
    @contextmanager
    def _transaction(conn: sqlite3.Connection) -> Iterator[None]:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")

    def remember(
        self,
        *,
        kind: str,
        scope: str,
        stable_key: str,
        content: str,
        evidence_type: str,
        evidence_ref: str,
        trigger: str | None = None,
        paths: Sequence[str] = (),
    ) -> MemoryEntry:
        if scope not in SCOPES:
            raise MemoryValidationError(f"unknown scope: {scope}")
        if kind not in KINDS:
            raise MemoryValidationError(f"unknown kind: {kind}")
        if evidence_type not in EVIDENCE_TYPES:
            raise MemoryValidationError(f"unknown evidence_type: {evidence_type}")
        key = _stable_key(stable_key)
        body = _required_text(content, "content")
        evidence = _required_text(evidence_ref, "evidence_ref")
        normalized_paths = _paths(paths)
        if scope == "long_term" and normalized_paths:
            raise MemoryValidationError("long_term entries cannot carry paths")
        if kind == "behavior":
            normalized_trigger = _required_text(trigger or "", "trigger")
        elif trigger is not None:
            raise MemoryValidationError("definition must not carry a trigger")
        else:
            normalized_trigger = ""
        project_key = self._project_key if scope == "project" else ""
        now = _now_iso()
        with self._connection() as conn:
            try:
                with self._transaction(conn):
                    row = self._active_semantic_row(conn, scope, project_key, kind, key)
                    if row is not None and bool(row["pinned"]):
                        raise MemoryConflictError(
                            "pinned memory must be unpinned before it can be updated"
                        )
                    if row is None:
                        cursor = conn.execute(
                            """
                            INSERT INTO semantic_entries (
                                scope, project_key, kind, stable_key, content,
                                trigger, evidence_type, evidence_ref, paths_json,
                                validated_at, created_at, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                scope,
                                project_key,
                                kind,
                                key,
                                body,
                                normalized_trigger,
                                evidence_type,
                                evidence,
                                json.dumps(normalized_paths),
                                now,
                                now,
                                now,
                            ),
                        )
                        if cursor.lastrowid is None:
                            raise MemoryConflictError(
                                "semantic memory insert returned no id"
                            )
                        entry_id = cursor.lastrowid
                    else:
                        entry_id = int(row["id"])
                        conn.execute(
                            """
                            UPDATE semantic_entries
                            SET content = ?, trigger = ?, evidence_type = ?,
                                evidence_ref = ?, paths_json = ?,
                                validated_at = ?, updated_at = ?
                            WHERE id = ?
                            """,
                            (
                                body,
                                normalized_trigger,
                                evidence_type,
                                evidence,
                                json.dumps(normalized_paths),
                                now,
                                now,
                                entry_id,
                            ),
                        )
                    return _memory_entry(self._semantic_row(conn, entry_id))
            except sqlite3.IntegrityError as exc:
                raise MemoryConflictError(
                    f"semantic memory write conflicted with current state: {exc}"
                ) from exc

    def get(self, entry_id: int) -> MemoryEntry | None:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM semantic_entries WHERE id = ?", (entry_id,)
            ).fetchone()
            if row is None or not self._semantic_visible(row):
                return None
            return _memory_entry(row)

    def recall_memory(
        self,
        query: str,
        *,
        project_root: Path | None = None,
        limit: int = MAX_MEMORY_RESULTS,
    ) -> list[MemoryEntry]:
        normalized_query = _required_text(query, "query")
        needle = _literal(normalized_query)
        exact_key = _stable_key(normalized_query)
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM semantic_entries
                WHERE archived_at IS NULL
                  AND (scope = 'long_term'
                    OR (scope = 'project' AND project_key = ?))
                ORDER BY stable_key, id
                """,
                (self._project_key,),
            ).fetchall()
        matches: list[tuple[bool, MemoryEntry]] = []
        for row in rows:
            entry = _memory_entry(row)
            if self.review_reasons(entry, project_root=project_root):
                continue
            fields = (entry.stable_key, entry.content, entry.trigger, *entry.paths)
            exact = entry.stable_key == exact_key
            if exact or any(needle in _literal(field) for field in fields):
                matches.append((exact, entry))
        matches.sort(key=lambda item: (not item[0], item[1].stable_key, item[1].id))
        return [entry for _, entry in matches[: max(0, limit)]]

    def pinned(self, *, project_root: Path | None = None) -> list[MemoryEntry]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM semantic_entries
                WHERE archived_at IS NULL AND pinned = 1
                  AND (scope = 'long_term'
                    OR (scope = 'project' AND project_key = ?))
                """,
                (self._project_key,),
            ).fetchall()
        entries: list[MemoryEntry] = []
        for row in rows:
            entry = _memory_entry(row)
            if not self.review_reasons(entry, project_root=project_root):
                entries.append(entry)
        kind_order = {"behavior": 0, "definition": 1}
        scope_order = {"project": 0, "long_term": 1}
        entries.sort(
            key=lambda entry: (
                kind_order[entry.kind],
                scope_order[entry.scope],
                entry.stable_key,
                entry.id,
            )
        )
        return entries

    def needs_review(
        self,
        *,
        project_root: Path | None = None,
        limit: int = MAX_REVIEW_RESULTS,
    ) -> list[ReviewEntry]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM semantic_entries
                WHERE archived_at IS NULL
                  AND (scope = 'long_term'
                    OR (scope = 'project' AND project_key = ?))
                ORDER BY validated_at, stable_key, id
                """,
                (self._project_key,),
            ).fetchall()
        result: list[ReviewEntry] = []
        for row in rows:
            entry = _memory_entry(row)
            reasons = self.review_reasons(entry, project_root=project_root)
            if reasons:
                result.append(ReviewEntry(entry=entry, reasons=reasons))
        return result[: max(0, limit)]

    @staticmethod
    def review_reasons(
        entry: MemoryEntry,
        *,
        project_root: Path | None,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        try:
            validated = datetime.fromisoformat(entry.validated_at)
            if validated.tzinfo is None:
                validated = validated.replace(tzinfo=UTC)
            if validated < datetime.now(UTC) - timedelta(days=MEMORY_REVIEW_AFTER_DAYS):
                reasons.append(f"validation older than {MEMORY_REVIEW_AFTER_DAYS} days")
        except ValueError:
            reasons.append("invalid validated_at")
        if entry.paths and project_root is None:
            reasons.append("project root unavailable for path validation")
        elif project_root is not None:
            reasons.extend(
                f"missing path: {path}"
                for path in entry.paths
                if not (project_root / path).exists()
            )
        return tuple(reasons)

    def archived_semantic(
        self, *, limit: int = MAX_REVIEW_RESULTS
    ) -> list[MemoryEntry]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM semantic_entries
                WHERE archived_at IS NOT NULL
                  AND (scope = 'long_term'
                    OR (scope = 'project' AND project_key = ?))
                ORDER BY archived_at DESC, id DESC LIMIT ?
                """,
                (self._project_key, max(0, limit)),
            ).fetchall()
        return [_memory_entry(row) for row in rows]

    def archive_semantic(self, entry_id: int) -> MemoryEntry:
        now = _now_iso()
        with self._connection() as conn, self._transaction(conn):
            row = self._visible_semantic_row(conn, entry_id)
            conn.execute(
                "UPDATE semantic_entries SET archived_at = ?, pinned = 0, "
                "updated_at = ? WHERE id = ?",
                (now, now, entry_id),
            )
            return _memory_entry(self._semantic_row(conn, int(row["id"])))

    def restore_semantic(self, entry_id: int) -> MemoryEntry:
        now = _now_iso()
        with self._connection() as conn:
            try:
                with self._transaction(conn):
                    row = self._visible_semantic_row(conn, entry_id)
                    if row["archived_at"] is None:
                        return _memory_entry(row)
                    conn.execute(
                        "UPDATE semantic_entries SET archived_at = NULL, "
                        "pinned = 0, updated_at = ? WHERE id = ?",
                        (now, entry_id),
                    )
                    return _memory_entry(self._semantic_row(conn, entry_id))
            except sqlite3.IntegrityError as exc:
                raise MemoryConflictError(
                    "cannot restore semantic memory because an active stable key exists"
                ) from exc

    def validate_semantic(
        self,
        entry_id: int,
        *,
        evidence_type: str,
        evidence_ref: str,
    ) -> MemoryEntry:
        if evidence_type not in EVIDENCE_TYPES:
            raise MemoryValidationError(f"unknown evidence_type: {evidence_type}")
        evidence = _required_text(evidence_ref, "evidence_ref")
        now = _now_iso()
        with self._connection() as conn, self._transaction(conn):
            self._visible_semantic_row(conn, entry_id)
            conn.execute(
                "UPDATE semantic_entries SET evidence_type = ?, evidence_ref = ?, "
                "validated_at = ?, updated_at = ? WHERE id = ?",
                (evidence_type, evidence, now, now, entry_id),
            )
            return _memory_entry(self._semantic_row(conn, entry_id))

    def set_pinned(self, entry_id: int, *, pinned: bool) -> MemoryEntry:
        if not isinstance(pinned, bool):
            raise MemoryValidationError("pinned must be a boolean")
        now = _now_iso()
        with self._connection() as conn, self._transaction(conn):
            row = self._visible_semantic_row(conn, entry_id)
            if row["archived_at"] is not None:
                raise MemoryConflictError("archived semantic memory cannot be pinned")
            conn.execute(
                "UPDATE semantic_entries SET pinned = ?, updated_at = ? WHERE id = ?",
                (int(pinned), now, entry_id),
            )
            return _memory_entry(self._semantic_row(conn, entry_id))

    def purge_semantic(self, entry_id: int) -> None:
        with self._connection() as conn, self._transaction(conn):
            self._visible_semantic_row(conn, entry_id)
            conn.execute("DELETE FROM semantic_entries WHERE id = ?", (entry_id,))

    def remember_task(
        self,
        *,
        stable_key: str,
        title: str,
        objective: str,
        summary: str,
        next_action: str,
        refs: Sequence[str] = (),
    ) -> TaskEntry:
        key = _stable_key(stable_key)
        title = _required_text(title, "title")
        objective = _required_text(objective, "objective")
        summary = _required_text(summary, "summary")
        next_action = _required_text(next_action, "next_action")
        normalized_refs = _string_list(refs, "refs")
        now = _now_iso()
        with self._connection() as conn, self._transaction(conn):
            row = self._active_task_row(conn, key)
            if row is None:
                cursor = conn.execute(
                    """
                    INSERT INTO tasks (
                        project_key, stable_key, title, objective, summary,
                        next_action, refs_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._project_key,
                        key,
                        title,
                        objective,
                        summary,
                        next_action,
                        json.dumps(normalized_refs),
                        now,
                        now,
                    ),
                )
                if cursor.lastrowid is None:
                    raise MemoryConflictError("task insert returned no id")
                task_id = cursor.lastrowid
            else:
                task_id = int(row["id"])
                conn.execute(
                    """
                    UPDATE tasks SET title = ?, objective = ?, summary = ?,
                        next_action = ?, refs_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        title,
                        objective,
                        summary,
                        next_action,
                        json.dumps(normalized_refs),
                        now,
                        task_id,
                    ),
                )
            return _task_entry(self._task_row(conn, task_id))

    def recall_tasks(
        self,
        *,
        stable_key: str | None = None,
        status: str = "open",
        limit: int = MAX_TASK_RESULTS,
    ) -> list[TaskEntry]:
        if status not in ("open", "completed", "all"):
            raise MemoryValidationError(f"unknown task status: {status}")
        clauses = ["project_key = ?", "archived_at IS NULL"]
        parameters: list[object] = [self._project_key]
        if stable_key is not None:
            clauses.append("stable_key = ?")
            parameters.append(_stable_key(stable_key))
        if status != "all":
            clauses.append("status = ?")
            parameters.append(status)
        parameters.append(max(0, limit))
        with self._connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM tasks WHERE {' AND '.join(clauses)} "
                "ORDER BY updated_at DESC, stable_key ASC LIMIT ?",
                parameters,
            ).fetchall()
        return [_task_entry(row) for row in rows]

    def archived_tasks(self, *, limit: int = MAX_REVIEW_RESULTS) -> list[TaskEntry]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tasks
                WHERE project_key = ? AND archived_at IS NOT NULL
                ORDER BY archived_at DESC, id DESC LIMIT ?
                """,
                (self._project_key, max(0, limit)),
            ).fetchall()
        return [_task_entry(row) for row in rows]

    def complete_task(self, task_id: int) -> TaskEntry:
        return self._set_task_status(task_id, "completed")

    def reopen_task(self, task_id: int) -> TaskEntry:
        return self._set_task_status(task_id, "open")

    def _set_task_status(self, task_id: int, status: TaskStatus) -> TaskEntry:
        now = _now_iso()
        with self._connection() as conn, self._transaction(conn):
            self._visible_task_row(conn, task_id)
            conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, task_id),
            )
            return _task_entry(self._task_row(conn, task_id))

    def archive_task(self, task_id: int) -> TaskEntry:
        now = _now_iso()
        with self._connection() as conn, self._transaction(conn):
            self._visible_task_row(conn, task_id)
            conn.execute(
                "UPDATE tasks SET archived_at = ?, updated_at = ? WHERE id = ?",
                (now, now, task_id),
            )
            return _task_entry(self._task_row(conn, task_id))

    def restore_task(self, task_id: int) -> TaskEntry:
        now = _now_iso()
        with self._connection() as conn:
            try:
                with self._transaction(conn):
                    row = self._visible_task_row(conn, task_id)
                    if row["archived_at"] is None:
                        return _task_entry(row)
                    conn.execute(
                        "UPDATE tasks SET archived_at = NULL, updated_at = ? "
                        "WHERE id = ?",
                        (now, task_id),
                    )
                    return _task_entry(self._task_row(conn, task_id))
            except sqlite3.IntegrityError as exc:
                raise MemoryConflictError(
                    "cannot restore task because an active stable key exists"
                ) from exc

    def purge_task(self, task_id: int) -> None:
        with self._connection() as conn, self._transaction(conn):
            self._visible_task_row(conn, task_id)
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    @staticmethod
    def _active_semantic_row(
        conn: sqlite3.Connection,
        scope: str,
        project_key: str,
        kind: str,
        stable_key: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT * FROM semantic_entries
            WHERE scope = ? AND project_key = ? AND kind = ?
              AND stable_key = ? AND archived_at IS NULL
            """,
            (scope, project_key, kind, stable_key),
        ).fetchone()

    @staticmethod
    def _semantic_row(conn: sqlite3.Connection, entry_id: int) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM semantic_entries WHERE id = ?", (entry_id,)
        ).fetchone()
        if row is None:
            raise MemoryConflictError(f"semantic memory not found: {entry_id}")
        return row

    def _visible_semantic_row(
        self, conn: sqlite3.Connection, entry_id: int
    ) -> sqlite3.Row:
        row = self._semantic_row(conn, entry_id)
        if not self._semantic_visible(row):
            raise MemoryConflictError(f"semantic memory not found: {entry_id}")
        return row

    def _semantic_visible(self, row: sqlite3.Row) -> bool:
        return row["scope"] == "long_term" or row["project_key"] == self._project_key

    def _active_task_row(
        self, conn: sqlite3.Connection, stable_key: str
    ) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM tasks WHERE project_key = ? AND stable_key = ? "
            "AND archived_at IS NULL",
            (self._project_key, stable_key),
        ).fetchone()

    @staticmethod
    def _task_row(conn: sqlite3.Connection, task_id: int) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise MemoryConflictError(f"task not found: {task_id}")
        return row

    def _visible_task_row(self, conn: sqlite3.Connection, task_id: int) -> sqlite3.Row:
        row = self._task_row(conn, task_id)
        if row["project_key"] != self._project_key:
            raise MemoryConflictError(f"task not found: {task_id}")
        return row


def default_memory_db_path() -> Path:
    return Path.home() / ".lion-code" / "memory.sqlite3"
