# Memory Capability Contract

## 1. Scope / Trigger

This contract applies when FullProfile exposes cross-session project tasks or
stable semantic knowledge. Memory is a Capability-private component, not a
Session history, repository index, AGENTS copy, Trellis adapter, or enforcement
hook.

The current contract covers the canonical SQLite store, explicit tools, static
MemoryPolicy, and an ordinary prepared-only ContextLayer for reviewed pinned
entries. Automatic query-aware recall is not part of phase one.

## 2. Signatures

The storage constructor is side-effect free:

```python
MemoryStore(db_path: Path, *, project_key: str)
```

The first actual operation creates or validates exactly these canonical tables:

```text
semantic_entries(
  id, scope, project_key, kind, stable_key, content, trigger, pinned,
  evidence_type, evidence_ref, paths_json, validated_at,
  created_at, updated_at, archived_at
)

tasks(
  id, project_key, stable_key, title, objective, summary, next_action,
  status, refs_json, created_at, updated_at, archived_at
)
```

Each table has one partial unique index for its active stable key, where
`archived_at IS NULL`.

The model-visible tool surface is:

```text
remember_task          mutation, no confirmation
recall_tasks           read-only, parallel-safe
remember_definition    mutation, no confirmation
remember_behavior      mutation, no confirmation
recall_memory           read-only, parallel-safe
review_memory           read-only, parallel-safe
manage_memory           reversible mutation, no confirmation
set_memory_pinned       mutation, confirmation required
purge_memory            irreversible mutation, confirmation required
```

## 3. Contracts

- One SQLite file stores all projects; every project read/write filters by the
  current `ProjectIdentity.key`. Long-term semantic entries use an empty
  `project_key` and remain visible across projects.
- A task is a project-scoped work object with `open|completed` status. It stores
  an objective, bounded progress summary, next action, and references; it never
  stores transcript or per-turn tool output.
- Semantic classification is only `long_term|project × definition|behavior`.
  Definition has no trigger. Behavior has a non-empty trigger and stores its
  instruction in `content`.
- Every semantic write has exactly one `user_request|source|test|command`
  evidence reference. Stable keys are trimmed, whitespace-collapsed, and
  case-folded before persistence.
- Persisted lifecycle is only active (`archived_at IS NULL`) or archived.
  `needs_review` is derived at read time when validation is older than 90 days,
  any recorded path is missing, or a path cannot be checked because the project
  root is unavailable.
- Explicit semantic recall is bounded exact-key or literal matching and excludes
  archived or needs-review entries. Phase one has no FTS table, BM25, revision
  graph, recall counter, or query-aware context layer.
- The ordinary pinned ContextLayer includes at most eight whole reviewed
  entries, including its heading and authority-priority notice, within 512
  estimated tokens. An oversized entry is skipped rather than blocking later
  entries; no eligible entry means no injected block. Its output states that
  current user instructions, AGENTS, source, and tests take priority, remains
  request-local, and never reaches canonical history, JSONL, CompactionEntry,
  or compactor input.
- Updating an active stable key changes the same row. A pinned semantic row must
  be confirmed-unpinned first. Archive clears `pinned`; restore never restores
  it. Validate requires new typed evidence.
- MemoryPolicy tells the model when to recall tasks, when a significant task
  change deserves a write, semantic eligibility, and authority priority. It
  contains no project rules or dynamic memory content.

## 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Constructor only | No directory or database file is created |
| First pinned render | Lazily opens/validates the database; schema errors fail explicitly |
| Fresh concurrent first open | One canonical schema is committed; all callers continue |
| Unknown `user_version`, extra/missing table or column, corrupt file | `MemorySchemaError` including the database path; original file is preserved |
| Unknown evidence type, empty reference, invalid kind/trigger, unsafe path | `MemoryValidationError`; no row is written |
| Remember targets a pinned active key | `MemoryConflictError`; pinned content is unchanged |
| Restore collides with an active stable key | `MemoryConflictError`; both existing rows are unchanged |
| Path is missing or validation is old | Entry appears in `needs_review` and exits explicit recall without a status write |
| Expected tool/store failure | `ToolResult(is_error=True)` through `ToolRuntime`, not an empty-success result |
| Pin, unpin, or purge in default permission mode | Existing confirmation middleware decides before execution |

## 5. Good / Base / Bad Cases

- Good: a clean Session calls `recall_tasks`, receives the current project's
  open tasks, selects one, and then checks its references against current code.
- Base: a non-pinned definition with typed source evidence is updated in place
  after a significant change; no background extractor or second model runs.
- Bad: copy a Session compaction summary into Memory, cache repository
  architecture, persist a `stale` state, or silently rebuild an unknown database.

## 6. Tests Required

- `tests/capabilities/test_memory_store.py` asserts lazy and concurrent open,
  exact schema/columns, corruption/version failure, Task Ledger 0/1/N and project
  isolation, four semantic quadrants, stable-key normalization, lifecycle
  conflicts, typed evidence, and dynamic review exclusion.
- `tests/capabilities/test_memory_capability.py` asserts the exact nine-tool
  surface, ToolCapabilities, MemoryPolicy, structured failures, task result
  bounds, archived views, validate evidence, pin/purge confirmation, and pinned
  prepared-only projection bounds.
- `tests/architecture/test_memory_capability_boundaries.py` asserts FullProfile
  construction is lazy, Runtime owners cannot reach `MemoryStore`, the Memory
  package imports no Provider/Runtime owner, and Memory registers only the
  ordinary ContextLayer slot.
- Composition, PromptLayer, legacy-removal, and all architecture tests remain
  green after any schema or tool change.

## 7. Wrong vs Correct

Wrong:

```python
store = MemoryStore(path, project_key=key)  # creates or repairs the DB here
store.remember(..., evidence=["anything"], recall_mode="relevant")
```

Correct:

```python
store = MemoryStore(path, project_key=key)  # side-effect free
store.remember(
    kind="definition",
    scope="project",
    stable_key="ci-policy",
    content="CI must pass before merge",
    evidence_type="source",
    evidence_ref="docs/ci.md",
)
```

The first operation validates one exact canonical schema. An incompatible file
is reported for explicit user disposition; it is never migrated, renamed,
purged, or replaced automatically.
