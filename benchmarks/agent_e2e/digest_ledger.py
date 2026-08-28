"""digest 寻迹数据库：digest → 脱敏摘要与时间的本地 append-only 记账。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .models import VersionedModel, utc_now
from .trace import redact_text

LEDGER_SCHEMA_VERSION = "digest-ledger/v1"
# 预留的敏感字段名防线；实际预览值统一由 redacted_preview 脱敏后写入。
_FORBIDDEN_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "cookie",
    "password",
    "secret",
    "session",
    "token",
)


class DigestLedgerEntry(VersionedModel):
    """一条 digest 寻迹记录；preview 只存脱敏摘要，不存原始正文。"""

    digest: str = Field(min_length=64, max_length=64)
    kind: Literal["input", "trace", "payload", "argument"]
    task_id: str | None = Field(default=None, max_length=160)
    run_id: str | None = Field(default=None, max_length=128)
    event_type: str | None = Field(default=None, max_length=160)
    tool_name: str | None = Field(default=None, max_length=160)
    preview: str | None = Field(default=None, max_length=320)
    first_seen_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)
    count: int = Field(default=1, ge=1)


class DigestLedger:
    """append-only JSONL 寻迹账本：只追加、按行读，聚合在查询时进行。

    每行是一条 ``DigestLedgerEntry`` 的 canonical JSON；首行为
    schema 头。单机本用户运维场景下追加写足够原子，不引入数据库依赖。
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def append(self, entries: Sequence[DigestLedgerEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            if self.path.stat().st_size == 0:
                handle.write(
                    json.dumps(
                        {
                            "schema_version": LEDGER_SCHEMA_VERSION,
                            "kind": "digest-ledger",
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )
            for entry in entries:
                _reject_sensitive_entry(entry)
                handle.write(entry.canonical_json() + "\n")

    def lookup(
        self,
        digest: str,
        *,
        limit: int = 50,
    ) -> tuple[DigestLedgerEntry, ...]:
        """按 digest 反查：每 (digest, kind) 取最近一条，count 跨出现聚合。"""

        if not self.path.is_file():
            return ()
        latest: dict[str, DigestLedgerEntry] = {}
        counts: dict[str, int] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict) or payload.get("kind") == "digest-ledger":
                continue
            if payload.get("digest") != digest:
                continue
            try:
                entry = DigestLedgerEntry.model_validate(payload)
            except ValueError:
                continue
            key = entry.kind
            counts[key] = counts.get(key, 0) + entry.count
            previous = latest.get(key)
            if previous is None or entry.last_seen_at > previous.last_seen_at:
                latest[key] = entry
        return tuple(
            sorted(
                (
                    entry.model_copy(update={"count": counts[key]})
                    for key, entry in latest.items()
                ),
                key=lambda item: item.last_seen_at,
                reverse=True,
            )
        )[:limit]

    def count(self) -> int:
        """返回账本中的数据行数(schema 头不计)。"""

        if not self.path.is_file():
            return 0
        total = 0
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("kind") == "digest-ledger":
                continue
            total += 1
        return total


def _reject_sensitive_entry(entry: DigestLedgerEntry) -> None:
    """写入口防线：条目不得携带敏感字段名；预览值须已脱敏。"""

    value: Any
    for key, value in entry.model_dump(mode="json").items():
        if any(part in str(key).casefold() for part in _FORBIDDEN_KEY_PARTS):
            raise ValueError(f"digest ledger field is sensitive: {key}")


def redacted_preview(value: str, *, max_length: int = 320) -> str | None:
    """统一入口：把任意文本脱敏为受控预览，空串返回 None。"""

    if not value:
        return None
    preview, _ = redact_text(value, max_length=max_length)
    return preview or None


__all__ = (
    "LEDGER_SCHEMA_VERSION",
    "DigestLedger",
    "DigestLedgerEntry",
    "redacted_preview",
)
