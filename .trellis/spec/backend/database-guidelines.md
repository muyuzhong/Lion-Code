# Persistence Guidelines

> Lion Code does not use a relational database, ORM, SQL query layer, or
> database-migration tool.  Its durable runtime state is local, append-only JSONL
> session storage.  Treat this as a persistence contract, not as an invitation to
> introduce database conventions that are absent from the repository.

## Current storage model

- `lion_code/session_runtime/repository.py::SessionRepository` locates and
  replays sessions under `~/.lion-code/sessions/<session-id>.jsonl`.
- `lion_code/session_runtime/recorder.py::SessionRecorder` is the runtime writer.
  It serializes completed Core messages, model/thinking changes and compaction
  entries in event order.
- `lion_code/core/session/storage.py::JsonlSessionStorage` owns append/read I/O;
  `lion_code/core/session/jsonl.py` owns strict Pydantic validation and persisted
  Lion-v1 record migration.
- `lion_code/session_runtime/legacy.py` reads old `<session-id>.json` files only
  so they can be converted into canonical messages.  New sessions continue in
  JSONL; legacy source files are not a write target.

## Read and write patterns

```python
# Read/replay through the repository.
state = await repository.load(session_id)

# Obtain the storage for a safe session id; SessionRecorder owns normal writes.
storage = repository.storage_for(session_id)
await recorder.record_message(message)
```

- Keep public repository operations asynchronous (`load`, `list_sessions`,
  `latest_session_id`) and use `SessionState.from_entries(...)` for replay.
- Use `SessionRepository.storage_for()` rather than building session paths at
  call sites.  It rejects empty IDs, `.` / `..`, and path-like values before it
  creates `<id>.jsonl`.
- Use `SessionRecorder` for normal runtime writes.  It holds one `asyncio.Lock`,
  restores the parent/context position before writing, and delegates each entry
  to `JsonlSessionStorage.append()`.
- JSONL is append-only.  Each append creates parent directories, writes UTF-8
  canonical JSON plus a newline, flushes, and calls `fsync`.  If a process left
  a partial final line, `JsonlSessionStorage` discards that incomplete tail before
  the next append; it does not rewrite valid prior entries.

## Compatibility and migration

- Persisted entry compatibility is intentionally confined to
  `lion_code/core/session/jsonl.py::_migrate_session_entry`; runtime models keep
  one strict canonical wire shape.
- A malformed UTF-8 completed record or invalid entry becomes
  `SessionJsonlError`.  A final tail without a newline is instead treated as an
  incomplete record and discarded.  Listing sessions catches `OSError`,
  `SessionJsonlError`, and `ValueError` per file and skips that row; direct
  loading can surface the error to its caller.
- `session_runtime/legacy.py` reads and converts legacy JSON into canonical
  messages; `Agent.restore_session_id()` writes the separate JSONL migration.
  It does not rewrite the original `<session-id>.json`, preserving its filename,
  bytes and modification time.  If JSONL and legacy JSON use the same ID, JSONL
  is authoritative.

## Naming and migration conventions

- The canonical filename is `<safe-session-id>.jsonl`; the legacy filename is
  `<safe-session-id>.json`.
- Session entries use the canonical Core/Pi-compatible wire shape serialized by
  `entry_to_json_line()`, not ad-hoc dictionaries or a second provider history.
- There are no SQL table/column/index naming rules and no Alembic-style migration
  workflow.  Do not add ORM models or database migrations to change the existing
  local-session format; make an explicit persistence design change instead.

## Common mistakes to avoid

- Writing a monolithic `.json` snapshot for a new session or treating the legacy
  reader as a second live writer.
- Bypassing `SessionRecorder` from the TUI, provider, or a sub-agent and thereby
  breaking entry ordering or session replay.
- Rewriting a legacy file during migration; it is the user's rollback copy.
- Parsing JSONL outside `JsonlSessionStorage` / `SessionJsonlError` and silently
  accepting malformed persisted data.

## Representative tests

- `tests/session_runtime/test_repository.py` covers repository validation,
  listing and JSONL loading behavior.
- `tests/session_runtime/test_recorder.py` covers append/replay ordering and
  recorder state.
- `tests/session_runtime/test_legacy_fallback.py` covers the legacy JSON boundary.
