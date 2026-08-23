"""Semantic Memory 的 SQLite 存储：schema、revision 生命周期与检索。

存储契约（设计文档 4/5 节）：

- 单库 ``~/.lion-code/memory.sqlite3`` 容纳 long_term 与所有 project，
  通过 ``project_key`` 硬隔离，不按 scope 建 repository；
- FTS 只索引 active/stale；archived 与被 supersede 的 revision 退出索引；
- 修正同一 stable key 走「新 active revision + 旧 revision archived」，
  不按时间戳自动判真；
- schema 不匹配或 integrity check 失败时 fail closed，绝不重建覆盖。
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from ...context.estimator import estimate_text_tokens

MemoryScope = Literal["long_term", "project"]
MemoryKind = Literal["definition", "behavior"]
MemoryRecallMode = Literal["pinned", "relevant"]
MemoryStatus = Literal["active", "stale", "archived"]
ManageAction = Literal["mark_stale", "archive", "restore", "validate", "purge"]

SCHEMA_VERSION = 1
# WAL 下并发读写靠 busy_timeout 重试；5s 覆盖个人规模的所有正常写事务
BUSY_TIMEOUT_MS = 5000
# recall 流水线常量：BM25 之上的固定 boost、lexical 门槛、返回上限
EXACT_KEY_BOOST = 10.0
EXACT_PATH_BOOST = 10.0
MIN_LEXICAL_HITS = 1
DEFAULT_TOP_K = 6
DEFAULT_TOKEN_BUDGET = 800
PINNED_TOKEN_BUDGET = 400
# 自动召回总注入上限：pinned 与 relevant 预算之和（设计 6.2）
TOTAL_TOKEN_BUDGET = 1200
DEFAULT_REVIEW_OLDER_THAN_DAYS = 90

SCOPES: tuple[str, ...] = ("long_term", "project")
KINDS: tuple[str, ...] = ("definition", "behavior")
RECALL_MODES: tuple[str, ...] = ("pinned", "relevant")
MANAGE_ACTIONS: tuple[str, ...] = (
    "mark_stale",
    "archive",
    "restore",
    "validate",
    "purge",
)

_SCHEMA_SQL = (
    """
    CREATE TABLE memory_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE memory_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        scope TEXT NOT NULL CHECK (scope IN ('long_term', 'project')),
        project_key TEXT,
        kind TEXT NOT NULL CHECK (kind IN ('definition', 'behavior')),
        stable_key TEXT NOT NULL CHECK (length(trim(stable_key)) > 0),
        content TEXT NOT NULL CHECK (length(trim(content)) > 0),
        trigger TEXT,
        recall_mode TEXT NOT NULL DEFAULT 'relevant'
            CHECK (recall_mode IN ('pinned', 'relevant')),
        status TEXT NOT NULL DEFAULT 'active'
            CHECK (status IN ('active', 'stale', 'archived')),
        evidence_json TEXT NOT NULL CHECK (
            json_valid(evidence_json) AND json_array_length(evidence_json) > 0
        ),
        paths_json TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(paths_json)),
        source_session_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        validated_at TEXT,
        supersedes_id INTEGER REFERENCES memory_entries(id) ON DELETE SET NULL,
        archived_reason TEXT,
        CHECK ((scope = 'project'
                AND project_key IS NOT NULL
                AND length(trim(project_key)) > 0)
            OR (scope = 'long_term' AND project_key IS NULL)),
        CHECK ((kind = 'behavior'
                AND trigger IS NOT NULL
                AND length(trim(trigger)) > 0)
            OR (kind = 'definition' AND trigger IS NULL)),
        CHECK (scope = 'project' OR paths_json = '[]')
    )
    """,
    # coalesce 保证 long_term（project_key 为 NULL）也参与唯一性；
    # NULL 在 SQLite 唯一索引中互不相等，直接列索引挡不住重复
    """
    CREATE UNIQUE INDEX memory_active_stable_key
    ON memory_entries (scope, coalesce(project_key, ''), kind, stable_key)
    WHERE status = 'active'
    """,
    """
    CREATE VIRTUAL TABLE memory_fts USING fts5(
        stable_key, content, trigger, paths
    )
    """,
)
_EXPECTED_OBJECTS = frozenset(
    {
        "memory_meta",
        "memory_entries",
        "memory_active_stable_key",
        "memory_fts",
    }
)
_TERM_PATTERN = re.compile(r"[^\W_]+")


def _query_contains(query: str, needle: str) -> bool:
    """exact key/path boost 的边界匹配：needle 作为完整词段出现在 query 中。"""
    return bool(re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", query, re.IGNORECASE))


class MemoryStoreError(Exception):
    """Memory 存储层错误基类。"""


class MemorySchemaError(MemoryStoreError):
    """schema 版本不匹配、对象缺失或 integrity check 失败（fail closed）。"""


class MemoryValidationError(MemoryStoreError):
    """调用方参数违反四象限契约（scope/paths/trigger/evidence）。"""


class MemoryConflictError(MemoryStoreError):
    """目标条目不存在或生命周期转换与 active 唯一性冲突。"""


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    """一条 memory revision 的不可变投影。"""

    id: int
    scope: MemoryScope
    project_key: str | None
    kind: MemoryKind
    stable_key: str
    content: str
    trigger: str | None
    recall_mode: MemoryRecallMode
    status: MemoryStatus
    evidence: tuple[str, ...]
    paths: tuple[str, ...]
    source_session_id: str | None
    created_at: str
    updated_at: str
    validated_at: str | None
    supersedes_id: int | None
    archived_reason: str | None

    def display_path(self) -> str:
        owner = self.project_key if self.scope == "project" else "long_term"
        return f"{owner}/{self.kind}"


@dataclass(frozen=True, slots=True)
class MemoryHit:
    """recall 检索结果：条目与确定性得分。"""

    entry: MemoryEntry
    score: float


@dataclass(frozen=True, slots=True)
class ReviewStaleCandidate:
    """paths 全部失效的 active 条目；只供 review，不自动改库。"""

    entry_id: int
    stable_key: str
    scope: MemoryScope
    missing_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RevisionChain:
    """一个 stable key 的 active revision 与其被替代的祖先链。"""

    active_id: int
    stable_key: str
    superseded_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ReviewReport:
    """review_memory 的治理视图聚合。"""

    scope: str
    older_than_days: int
    stale: tuple[MemoryEntry, ...]
    stale_candidates: tuple[ReviewStaleCandidate, ...]
    long_unvalidated: tuple[MemoryEntry, ...]
    pinned_overflow: tuple[MemoryEntry, ...]
    pinned_tokens: int
    pinned_token_budget: int
    revision_chains: tuple[RevisionChain, ...]
    archived_count: int


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _extract_terms(query: str) -> list[str]:
    return _TERM_PATTERN.findall(query)


def _row_entry(row: sqlite3.Row) -> MemoryEntry:
    return MemoryEntry(
        id=int(row["id"]),
        scope=row["scope"],
        project_key=row["project_key"],
        kind=row["kind"],
        stable_key=row["stable_key"],
        content=row["content"],
        trigger=row["trigger"],
        recall_mode=row["recall_mode"],
        status=row["status"],
        evidence=tuple(json.loads(row["evidence_json"])),
        paths=tuple(json.loads(row["paths_json"])),
        source_session_id=row["source_session_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        validated_at=row["validated_at"],
        supersedes_id=(
            int(row["supersedes_id"]) if row["supersedes_id"] is not None else None
        ),
        archived_reason=row["archived_reason"],
    )


class MemoryStore:
    """Capability 私有的 SQLite semantic memory 存储。

    每个操作持有独立连接：WAL 允许并发读 + 单写者，线程安全不需要
    实例级锁；写入统一走 IMMEDIATE 事务保证 revision 原子性。
    """

    def __init__(self, db_path: Path, *, project_key: str) -> None:
        if not project_key:
            raise MemoryValidationError("project_key must be non-empty")
        self._db_path = db_path
        self._project_key = project_key
        self._init_lock = threading.Lock()
        self._initialize()

    @property
    def db_path(self) -> Path:
        return self._db_path

    @property
    def project_key(self) -> str:
        return self._project_key

    # ------------------------------------------------------------------
    # 初始化与 fail-closed 校验
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._db_path,
            timeout=BUSY_TIMEOUT_MS / 1000,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._init_lock:
            try:
                conn = self._connect()
            except sqlite3.Error as exc:
                raise MemorySchemaError(
                    f"cannot open memory database {self._db_path}: {exc}"
                ) from exc
            try:
                objects = self._existing_objects(conn)
                if not objects:
                    self._create_schema(conn)
                else:
                    self._verify_existing(conn, objects)
            except sqlite3.Error as exc:
                raise MemorySchemaError(
                    f"memory database {self._db_path} failed validation: {exc}"
                ) from exc
            finally:
                conn.close()

    @staticmethod
    def _existing_objects(conn: sqlite3.Connection) -> set[str]:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {str(row[0]) for row in rows}

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        # 只有空库才允许建 schema；WAL 是库级持久属性，建库时设置一次
        conn.execute("PRAGMA journal_mode = WAL")
        with self._transaction(conn):
            for statement in _SCHEMA_SQL:
                conn.execute(statement)
            conn.execute(
                "INSERT INTO memory_meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    @staticmethod
    def _verify_existing(
        conn: sqlite3.Connection,
        objects: set[str],
    ) -> None:
        missing = _EXPECTED_OBJECTS - objects
        if missing:
            raise MemorySchemaError(
                f"memory database is missing expected objects: {sorted(missing)}"
            )
        row = conn.execute(
            "SELECT value FROM memory_meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is None or str(row[0]) != str(SCHEMA_VERSION):
            found = row[0] if row is not None else "missing"
            raise MemorySchemaError(
                f"memory database schema version mismatch: "
                f"expected {SCHEMA_VERSION}, found {found}"
            )
        integrity = conn.execute("PRAGMA integrity_check").fetchone()
        if integrity is None or str(integrity[0]) != "ok":
            detail = integrity[0] if integrity is not None else "no result"
            raise MemorySchemaError(f"memory database integrity check failed: {detail}")
        fk_violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_violations:
            raise MemorySchemaError(
                f"memory database foreign key check failed: {fk_violations}"
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

    # ------------------------------------------------------------------
    # 写入：remember 与 revision supersede
    # ------------------------------------------------------------------

    def remember(
        self,
        *,
        kind: str,
        scope: str,
        stable_key: str,
        content: str,
        evidence: Sequence[str],
        trigger: str | None = None,
        paths: Sequence[str] = (),
        recall_mode: str = "relevant",
        source_session_id: str | None = None,
    ) -> MemoryEntry:
        """写入一条 revision；同 identity 存在 active 时先 supersede。

        返回新 active revision；被替代 revision 置为 archived 并通过
        ``supersedes_id`` 链接到新条目。
        """
        self._validate_write(
            kind=kind,
            scope=scope,
            stable_key=stable_key,
            content=content,
            evidence=evidence,
            trigger=trigger,
            paths=paths,
            recall_mode=recall_mode,
        )
        project_key = self._project_key if scope == "project" else None
        now = _now_iso()
        conn = self._connect()
        try:
            with self._transaction(conn):
                current = self._active_row(conn, scope, project_key, kind, stable_key)
                supersedes_id: int | None = None
                if current is not None:
                    supersedes_id = int(current["id"])
                    self._set_status(
                        conn, current, "archived", reason="superseded", now=now
                    )
                conn.execute(
                    """
                    INSERT INTO memory_entries (
                        scope, project_key, kind, stable_key, content, trigger,
                        recall_mode, status, evidence_json, paths_json,
                        source_session_id, created_at, updated_at,
                        validated_at, supersedes_id
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        scope,
                        project_key,
                        kind,
                        stable_key,
                        content,
                        trigger,
                        recall_mode,
                        json.dumps(list(evidence)),
                        json.dumps(list(paths)),
                        source_session_id,
                        now,
                        now,
                        now,
                        supersedes_id,
                    ),
                )
                # 事务内 active 唯一性已保证该 identity 只剩新行，
                # 回读代替 lastrowid（其类型含 None）构造投影
                inserted = self._active_row(conn, scope, project_key, kind, stable_key)
                if inserted is None:
                    raise MemoryConflictError(
                        f"inserted revision for {stable_key} disappeared"
                    )
                entry = _row_entry(inserted)
                self._fts_index(conn, entry)
                return entry
        except sqlite3.IntegrityError as exc:
            raise MemoryValidationError(
                f"memory constraint rejected write: {exc}"
            ) from exc
        finally:
            conn.close()

    @staticmethod
    def _validate_write(
        *,
        kind: str,
        scope: str,
        stable_key: str,
        content: str,
        evidence: Sequence[str],
        trigger: str | None,
        paths: Sequence[str],
        recall_mode: str,
    ) -> None:
        MemoryStore._validate_enums(scope, kind, recall_mode)
        MemoryStore._validate_text(stable_key, content, evidence)
        MemoryStore._validate_trigger(kind, trigger)
        MemoryStore._validate_paths(scope, paths)

    @staticmethod
    def _validate_enums(scope: str, kind: str, recall_mode: str) -> None:
        if scope not in SCOPES:
            raise MemoryValidationError(f"unknown scope: {scope}")
        if kind not in KINDS:
            raise MemoryValidationError(f"unknown kind: {kind}")
        if recall_mode not in RECALL_MODES:
            raise MemoryValidationError(f"unknown recall_mode: {recall_mode}")

    @staticmethod
    def _validate_text(
        stable_key: str,
        content: str,
        evidence: Sequence[str],
    ) -> None:
        if not stable_key.strip():
            raise MemoryValidationError("stable_key must be non-empty")
        if not content.strip():
            raise MemoryValidationError("content must be non-empty")
        if not evidence or any(not item.strip() for item in evidence):
            raise MemoryValidationError("evidence must be a non-empty string list")

    @staticmethod
    def _validate_trigger(kind: str, trigger: str | None) -> None:
        """definition 与 behavior 的契约分离（设计 4.2）。"""
        if kind == "behavior" and (trigger is None or not trigger.strip()):
            raise MemoryValidationError("behavior requires a trigger")
        if kind == "definition" and trigger is not None:
            raise MemoryValidationError("definition must not carry a trigger")

    @staticmethod
    def _validate_paths(scope: str, paths: Sequence[str]) -> None:
        """project 可选携带项目相对 path；long_term 必须为空。"""
        if scope == "long_term" and paths:
            raise MemoryValidationError("long_term entries cannot carry paths")
        for path in paths:
            candidate = Path(path)
            if not path.strip() or path.strip() != path:
                raise MemoryValidationError("paths must be trimmed relative paths")
            if candidate.is_absolute() or ".." in candidate.parts:
                raise MemoryValidationError(
                    f"path must be project-relative without traversal: {path}"
                )

    @staticmethod
    def _active_row(
        conn: sqlite3.Connection,
        scope: str,
        project_key: str | None,
        kind: str,
        stable_key: str,
    ) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT * FROM memory_entries
            WHERE scope = ? AND project_key IS ? AND kind = ?
              AND stable_key = ? AND status = 'active'
            """,
            (scope, project_key, kind, stable_key),
        ).fetchone()

    @staticmethod
    def _fetch_row(conn: sqlite3.Connection, entry_id: int) -> sqlite3.Row | None:
        return conn.execute(
            "SELECT * FROM memory_entries WHERE id = ?", (entry_id,)
        ).fetchone()

    @staticmethod
    def _fts_index(conn: sqlite3.Connection, entry: MemoryEntry) -> None:
        conn.execute(
            "INSERT INTO memory_fts (rowid, stable_key, content, trigger, paths) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                entry.id,
                entry.stable_key,
                entry.content,
                entry.trigger or "",
                " ".join(entry.paths),
            ),
        )

    @staticmethod
    def _fts_delete(conn: sqlite3.Connection, entry_id: int) -> None:
        conn.execute("DELETE FROM memory_fts WHERE rowid = ?", (entry_id,))

    def _set_status(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        status: MemoryStatus,
        *,
        reason: str | None,
        now: str,
    ) -> MemoryEntry:
        """更新 revision 状态并维护 FTS 索引（archived 退出索引）。"""
        conn.execute(
            "UPDATE memory_entries SET status = ?, archived_reason = ?, "
            "updated_at = ? WHERE id = ?",
            (status, reason, now, row["id"]),
        )
        entry = _row_entry(row)
        self._fts_delete(conn, entry.id)
        if status != "archived":
            self._fts_index(conn, entry)
        return replace(
            entry,
            status=status,
            archived_reason=reason,
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # 治理：mark_stale / archive / restore / validate / purge
    # ------------------------------------------------------------------

    def manage(
        self,
        entry_id: int,
        action: str,
        *,
        reason: str | None = None,
    ) -> MemoryEntry | None:
        """执行治理动作；purge 物理删除并返回 None，其余返回更新后条目。"""
        if action not in MANAGE_ACTIONS:
            raise MemoryValidationError(f"unknown manage action: {action}")
        if action in ("mark_stale", "archive", "purge") and not (
            reason and reason.strip()
        ):
            raise MemoryValidationError(f"{action} requires a reason")
        now = _now_iso()
        conn = self._connect()
        try:
            with self._transaction(conn):
                row = self._fetch_row(conn, entry_id)
                if row is None or not self._row_visible(row):
                    raise MemoryConflictError(f"memory entry not found: {entry_id}")
                if action == "purge":
                    self._fts_delete(conn, entry_id)
                    conn.execute("DELETE FROM memory_entries WHERE id = ?", (entry_id,))
                    return None
                if action == "mark_stale":
                    return self._set_status(conn, row, "stale", reason=reason, now=now)
                if action == "archive":
                    return self._set_status(
                        conn, row, "archived", reason=reason, now=now
                    )
                if action == "restore":
                    return self._restore(conn, row, now=now)
                conn.execute(
                    "UPDATE memory_entries SET validated_at = ?, updated_at = ? "
                    "WHERE id = ?",
                    (now, now, entry_id),
                )
                return replace(
                    _row_entry(row),
                    validated_at=now,
                    updated_at=now,
                )
        finally:
            conn.close()

    def _restore(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
        *,
        now: str,
    ) -> MemoryEntry:
        if row["status"] == "active":
            return _row_entry(row)
        conflict = self._active_row(
            conn, row["scope"], row["project_key"], row["kind"], row["stable_key"]
        )
        if conflict is not None:
            raise MemoryConflictError(
                f"cannot restore: active revision {conflict['id']} already exists "
                f"for stable key {row['stable_key']}"
            )
        return self._set_status(conn, row, "active", reason=None, now=now)

    def _row_visible(self, row: sqlite3.Row) -> bool:
        """long_term 全可见；project 条目只对本 project_key 可见。"""
        return row["scope"] == "long_term" or row["project_key"] == self._project_key

    def get(self, entry_id: int) -> MemoryEntry | None:
        conn = self._connect()
        try:
            row = self._fetch_row(conn, entry_id)
            if row is None or not self._row_visible(row):
                return None
            return _row_entry(row)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 检索：FTS5 BM25 + boost + 硬过滤 + 门槛 + tie-break + top-k
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        include_inactive: bool = False,
        top_k: int = DEFAULT_TOP_K,
    ) -> list[MemoryHit]:
        """按当前 scope（long_term + 本 project）检索可管理条目。

        流水线：scope/status 硬过滤 → FTS5 BM25 → exact key/path boost →
        最低 lexical 门槛 → (-score, id) 稳定排序 → top-k。
        """
        terms = [term for term in _extract_terms(query) if len(term) > 1]
        if not terms:
            return []
        # 术语为纯字母数字 run，不含引号；加引号走 FTS5 短语语法
        match_query = " OR ".join(f'"{term}"' for term in terms)
        statuses: tuple[str, ...] = (
            ("active", "stale", "archived") if include_inactive else ("active",)
        )
        placeholders = ", ".join("?" * len(statuses))
        conn = self._connect()
        try:
            rows = conn.execute(
                f"""
                SELECT e.*, f.rank AS fts_rank
                FROM memory_fts f JOIN memory_entries e ON e.id = f.rowid
                WHERE memory_fts MATCH ?
                  AND e.status IN ({placeholders})
                  AND (e.scope = 'long_term'
                       OR (e.scope = 'project' AND e.project_key = ?))
                """,
                (match_query, *statuses, self._project_key),
            ).fetchall()
        finally:
            conn.close()
        hits: list[MemoryHit] = []
        for row in rows:
            entry = _row_entry(row)
            if self._lexical_hits(entry, terms) < MIN_LEXICAL_HITS:
                continue
            score = -float(row["fts_rank"])
            if _query_contains(query, entry.stable_key):
                score += EXACT_KEY_BOOST
            if any(_query_contains(query, path) for path in entry.paths):
                score += EXACT_PATH_BOOST
            hits.append(MemoryHit(entry=entry, score=score))
        hits.sort(key=lambda hit: (-hit.score, hit.entry.id))
        return hits[:top_k]

    @staticmethod
    def _lexical_hits(entry: MemoryEntry, terms: Sequence[str]) -> int:
        text = " ".join(
            (entry.stable_key, entry.content, entry.trigger or "", *entry.paths)
        )
        return sum(
            1
            for term in terms
            if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text, re.IGNORECASE)
        )

    # ------------------------------------------------------------------
    # 自动召回输入：pinned 集合与 relevant 检索
    # ------------------------------------------------------------------

    def pinned(self) -> list[MemoryEntry]:
        """long_term + 当前 project 的全部 active pinned 条目（id 升序）。

        供 QueryContextLayer 每次 prepared request 渲染；截断策略由调用方
        决定，本方法只做 scope/status 硬过滤。
        """
        return [
            entry
            for entry in self._visible_entries("all")
            if entry.status == "active" and entry.recall_mode == "pinned"
        ]

    # ------------------------------------------------------------------
    # Review：治理视图
    # ------------------------------------------------------------------

    def review(
        self,
        scope: str = "all",
        *,
        older_than_days: int = DEFAULT_REVIEW_OLDER_THAN_DAYS,
        project_root: Path | None = None,
    ) -> ReviewReport:
        """汇总 stale、stale candidate、长期未验证、pinned overflow 与 revision 链。"""
        if scope not in ("all", *SCOPES):
            raise MemoryValidationError(f"unknown scope: {scope}")
        if older_than_days < 0:
            raise MemoryValidationError("older_than_days must be non-negative")
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        entries = self._visible_entries(scope)
        pinned = tuple(
            entry
            for entry in entries
            if entry.status == "active" and entry.recall_mode == "pinned"
        )
        pinned_tokens = sum(estimate_text_tokens(entry.content) for entry in pinned)
        return ReviewReport(
            scope=scope,
            older_than_days=older_than_days,
            stale=tuple(entry for entry in entries if entry.status == "stale"),
            stale_candidates=self._stale_candidates(entries, project_root),
            long_unvalidated=tuple(
                entry
                for entry in entries
                if entry.status == "active" and self._is_stale_validation(entry, cutoff)
            ),
            pinned_overflow=pinned if pinned_tokens > PINNED_TOKEN_BUDGET else (),
            pinned_tokens=pinned_tokens,
            pinned_token_budget=PINNED_TOKEN_BUDGET,
            revision_chains=self._revision_chains(entries),
            archived_count=sum(1 for entry in entries if entry.status == "archived"),
        )

    @staticmethod
    def _is_stale_validation(entry: MemoryEntry, cutoff: datetime) -> bool:
        validated = _parse_iso(entry.validated_at)
        if validated is None:
            # 从未 validate 过的条目按创建时间计龄，避免永久漏报
            validated = _parse_iso(entry.created_at)
        return validated is None or validated < cutoff

    @staticmethod
    def _missing_paths(entry: MemoryEntry, project_root: Path) -> tuple[str, ...]:
        """确定性存在性校验（设计 7.2）：只判断，不读内容不执行。"""
        return tuple(path for path in entry.paths if not (project_root / path).exists())

    @staticmethod
    def _stale_candidates(
        entries: Sequence[MemoryEntry],
        project_root: Path | None,
    ) -> tuple[ReviewStaleCandidate, ...]:
        if project_root is None:
            return ()
        candidates: list[ReviewStaleCandidate] = []
        for entry in entries:
            if entry.status != "active" or not entry.paths:
                continue
            missing = MemoryStore._missing_paths(entry, project_root)
            if missing and len(missing) == len(entry.paths):
                candidates.append(
                    ReviewStaleCandidate(
                        entry_id=entry.id,
                        stable_key=entry.stable_key,
                        scope=entry.scope,
                        missing_paths=missing,
                    )
                )
        return tuple(candidates)

    @staticmethod
    def _revision_chains(entries: Sequence[MemoryEntry]) -> tuple[RevisionChain, ...]:
        by_id = {entry.id: entry for entry in entries}
        chains: list[RevisionChain] = []
        # 只从 active revision 出发回溯链；archived 中间节点不单独成链
        for entry in entries:
            if entry.status != "active":
                continue
            ancestors: list[int] = []
            cursor = entry.supersedes_id
            while cursor is not None and cursor in by_id:
                ancestors.append(cursor)
                cursor = by_id[cursor].supersedes_id
            if ancestors:
                chains.append(
                    RevisionChain(
                        active_id=entry.id,
                        stable_key=entry.stable_key,
                        superseded_ids=tuple(ancestors),
                    )
                )
        return tuple(chains)

    def _visible_entries(
        self,
        scope: str,
    ) -> list[MemoryEntry]:
        conn = self._connect()
        try:
            if scope == "long_term":
                rows = conn.execute(
                    "SELECT * FROM memory_entries WHERE scope = 'long_term' ORDER BY id"
                ).fetchall()
            elif scope == "project":
                rows = conn.execute(
                    "SELECT * FROM memory_entries WHERE scope = 'project' "
                    "AND project_key = ? ORDER BY id",
                    (self._project_key,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM memory_entries WHERE scope = 'long_term' "
                    "OR (scope = 'project' AND project_key = ?) ORDER BY id",
                    (self._project_key,),
                ).fetchall()
            return [_row_entry(row) for row in rows]
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # 路径存在性校验（recall 工具使用）
    # ------------------------------------------------------------------

    @staticmethod
    def partition_by_path_health(
        entries: Sequence[MemoryEntry],
        project_root: Path | None,
    ) -> tuple[list[MemoryEntry], list[ReviewStaleCandidate]]:
        """按 path 健康度拆分：全部失效的条目转为 stale candidate。"""
        if project_root is None:
            return list(entries), []
        healthy: list[MemoryEntry] = []
        candidates: list[ReviewStaleCandidate] = []
        for entry in entries:
            if not entry.paths:
                healthy.append(entry)
                continue
            missing = MemoryStore._missing_paths(entry, project_root)
            if missing and len(missing) == len(entry.paths):
                candidates.append(
                    ReviewStaleCandidate(
                        entry_id=entry.id,
                        stable_key=entry.stable_key,
                        scope=entry.scope,
                        missing_paths=missing,
                    )
                )
            else:
                healthy.append(entry)
        return healthy, candidates


def default_memory_db_path() -> Path:
    """返回默认数据库路径 ``~/.lion-code/memory.sqlite3``。"""
    return Path.home() / ".lion-code" / "memory.sqlite3"
