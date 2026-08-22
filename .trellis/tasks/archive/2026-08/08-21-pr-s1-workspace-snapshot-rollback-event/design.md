# PR-S1 Technical Design

## Architecture and owned modules

The recovery plane is a Tool Runtime concern. Add two focused modules:

- `lion_code/tooling/snapshot.py`: `WorkspaceSnapshot`, `SnapshotId`,
  `RestoreResult`, external tree capture, sensitive metadata, path protection,
  restore, and GC.
- `lion_code/tooling/audit.py`: `ExecutionEvent` and `ExecutionAuditLog`, the
  fixed event schema and append-only JSON-lines writer. Use a non-session file
  extension so the existing Session JSONL ownership guard remains true.

Extend only the existing Tool Runtime seams:

- `tooling/context.py`: optional snapshot/audit dependencies in the per-agent
  `ToolContext`.
- `tooling/middleware.py`: a pre-phase snapshot middleware keyed only by
  `ToolCapabilities`, and the existing post-phase audit callback wired to the
  new writer.
- `tooling/runtime.py`: a public `rollback()` operation that calls the injected
  `WorkspaceSnapshot` and returns a `ToolResult`; it is not a second tool
  execution loop.
- `tooling/types.py`: no new result model is required; existing `ToolResult`
  `details` carries snapshot and rollback metadata.
- `composition/bindings.py` and `composition/agent_builder.py`: injectable
  instances and independent enable switches; default instances are created in
  the Composition Root, never by Profiles or Agent Runtime owners.
- `tooling/__init__.py`: export the new public tooling contracts.

The forbidden files and packages remain untouched: `meta_agent.py`,
`runtime/conversation.py`, `runtime/session.py`, `runtime/context.py`, and
`capabilities/`.

## Data flow

```text
Core provider tool call
  -> adapter
  -> ToolRuntime.execute
  -> cancellation
  -> WorkspaceSnapshotMiddleware (only mutating/process tools)
  -> existing hook / permission / freshness middleware
  -> LionTool
  -> existing result policy
  -> existing AuditMiddleware -> ExecutionAuditLog
  -> ToolResult.details.snapshot_id + content
  -> Core ToolResultMessage
  -> next provider request
```

The snapshot middleware runs before hook/permission middleware so a relevant
tool call receives a snapshot regardless of whether a later existing policy
returns a blocked result. Cancellation remains first so an already-cancelled
call does not perform new I/O. The middleware catches operational snapshot
creation/tool exceptions at the existing structured-result boundary so the
post-audit stage still receives a result.

`ToolRuntime.rollback(snapshot_id, operation_summary)` is the only rollback
entry point. It calls `WorkspaceSnapshot.restore`, builds a result containing
the exact model-visible sentence and structured IDs, and appends a `rolled_back`
execution event on success. No conversation event, message injection, or
session write is added.

## WorkspaceSnapshot contract

```python
SnapshotId = str

class WorkspaceSnapshot:
    def create(self) -> SnapshotId: ...
    def restore(self, snapshot_id: SnapshotId) -> RestoreResult: ...
```

`RestoreResult` contains at least `restored`, `snapshot_id`,
`pre_restore_snapshot_id`, restored path information, and an optional error.
Snapshot creation captures a manifest and external tree:

1. Resolve the workspace root and, when present, the Git top-level root.
2. Read tracked paths from `HEAD` plus the current index and read non-ignored
   untracked paths through `git ls-files`; never mutate the index/worktree.
3. Capture ordinary file/symlink content outside the workspace. Record missing
   tracked paths as absence markers so tracked deletions restore correctly.
4. Enumerate ignored paths only for metadata and exclude any sensitive path from
   content capture. Sensitive matches include `.env*` path names and exact
   `.credentials` / `.secrets` path segments.
5. Write the manifest/data atomically enough for the local process, then run GC
   while protecting the newly created snapshot.

Restore first calls `create()` for the current state, then validates the target
manifest and materializes the target tree. Current non-ignored paths absent
from the target are removed; ignored/sensitive paths are never removed. All
path joins reject `.git`, absolute paths, and traversal outside the root. The
Git index and external resources are intentionally not restored.

GC retains snapshots that satisfy both the newest-N limit and the configured
retention window. A snapshot currently being created, restored, or used as a
pre-restore recovery point is temporarily protected from cleanup.

The snapshot store is outside the workspace. Parent/data permissions are
restricted best-effort (`0700`/`0600`) and storage roots are injectable so tests
never use the user's real data directory.

## ExecutionEvent schema

Define one typed event with exactly these fields:

```json
{
  "event": "execution",
  "tool": "...",
  "command_or_args": "...",
  "timestamp": "...",
  "snapshot_id": "...",
  "result": "success | failed | rolled_back | blocked",
  "destination": null,
  "fingerprint_hit": null,
  "authorization_source": null,
  "notes": []
}
```

`ExecutionAuditLog.append()` opens the configured file in append mode and writes
one UTF-8 JSON object per line. Tool execution uses `success`/`failed` in this
PR; the public writer accepts `blocked` for later policy integration. Rollback
uses `rolled_back`. `command_or_args` is a string: shell commands are preserved
as the command, while file-tool arguments are stable JSON with sensitive values
redacted (`content`, `old_string`, and `new_string` for sensitive targets).
The reserved fields remain `null`; notes contain only bounded, non-secret
status markers.

## Optional wiring and down state

Add to `ToolBindings`:

- optional `workspace_snapshot` instance,
- optional `audit_log` instance,
- `enable_workspace_snapshot: bool = True`,
- `enable_audit: bool = True`.

The builder creates default instances only when their switches are enabled;
injected instances always win. Disabled components produce no storage and do
not change existing results. `ToolContext.audit_fn` remains the existing
callback seam; the Composition Root supplies a closure to `ExecutionAuditLog`.

## Compatibility, rollback, and failure handling

- No migration is needed: new result metadata is optional and existing callers
  still construct `ToolContext` without the new services.
- With both switches false the old middleware behavior is preserved exactly.
- Snapshot creation failure returns `ToolResult(is_error=True)` and skips the
  unsnapshotted mutating/process tool call; audit records the failure if audit
  is enabled.
- Restore failure returns `RestoreResult(restored=False)` and retains the
  pre-restore snapshot ID for a subsequent caller retry/restore.
- A failed or partial restore does not silently claim success and does not
  auto-run a second rollback path.

## Test design

Unit tests cover tree capture/restore, untracked files, sensitive metadata,
`.git` protection, pre-restore IDs, GC, and audit schema/redaction. Tool Runtime
tests cover capability-triggered snapshots, repeated shell IDs, rollback result
text/details, audit results, and complete disablement. One Core integration test
asserts the rollback notice reaches `ToolResultMessage` and the fake provider's
next request without touching `runtime/conversation.py`.
