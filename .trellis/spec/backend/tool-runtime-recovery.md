# Tool Runtime Workspace Snapshot

## 1. Scope / Trigger

This contract applies to the workspace snapshot plane in `lion_code/tooling/`
and its Composition Root bindings. The trigger is a cross-layer tool result
contract: a mutating/process tool receives a workspace snapshot ID, and the
snapshot is available in `ToolResult.details` for audit and future recovery
tooling.

The plane contains `WorkspaceSnapshot`, the pre-phase
`WorkspaceSnapshotMiddleware`, and `ExecutionAuditLog`. It does not include a
rollback tool, a recovery manager, conversation injection channel, or a second
tool execution route.

## 2. Signatures

```python
SnapshotId = str

class WorkspaceSnapshot:
    def create(self) -> SnapshotId: ...
```

`ToolBindings` owns the optional concrete services and independent switches:

```python
workspace_snapshot: WorkspaceSnapshot | None = None
audit_log: ExecutionAuditLog | None = None
enable_workspace_snapshot: bool = True
enable_audit: bool = True
```

The Composition Root creates defaults lazily and keeps snapshot storage and the
audit destination outside the workspace. Tests and hosts may inject both
destinations.

## 3. Contracts

### Workspace snapshot contract

- `WorkspaceSnapshot.create()` captures tracked files, tracked absence
  markers, and non-ignored untracked files without changing the Git index or
  worktree. Git probes are read-only and scoped to the workspace path.
- Ignored files and `.env*`, `.credentials/`, and `.secrets/` paths receive
  only `exists`, `size`, and mtime metadata. Their contents never enter the
  snapshot tree. Snapshot directories are outside the workspace and use
  restrictive permissions where supported.
- `.git` is rejected by path validation and excluded from filesystem walks.
- GC keeps snapshots satisfying both the newest-N limit and the configured
  retention window.
- The pre-phase `WorkspaceSnapshotMiddleware` snapshots every tool whose
  `ToolCapabilities.mutates_workspace` or `.executes_process` is true. It does
  not inspect shell command text. The returned `ToolResult.details` contains
  `snapshot_id`.

### Audit contract

`ExecutionAuditLog` appends one UTF-8 JSON object per line to a dedicated
non-session `.audit` file. Every row has exactly this schema (additive
fields land as nullable columns, existing keys never rename):

```json
{
  "event": "execution",
  "tool": "...",
  "command_or_args": "...",
  "timestamp": "...",
  "snapshot_id": "...",
  "result": "success | failed | blocked",
  "destination": null,
  "fingerprint_hit": null,
  "authorization_source": null,
  "sanitizer_hits": 0,
  "best_effort": null,
  "notes": []
}
```

Execution results are recorded as `success`, `failed`, or `blocked` (for
egress blocks and budget-exceeded shutdowns). `sanitizer_hits`,
`destination`, `best_effort`, and `fingerprint_hit` are populated by the
corresponding middleware.

## 4. Validation & Error Matrix

| Condition | Required behavior |
|---|---|
| Snapshot creation fails while enabled | Return `ToolResult(is_error=True)` with no unsnapshotted tool execution; audit the failure when audit is enabled. |
| Tool raises after its pre-snapshot | Convert to the existing structured error boundary and retain `details.snapshot_id`. |
| Snapshot/audit switches are disabled | Do not create their services or storage; preserve ordinary ToolRuntime execution and result shape. |
| Snapshot path is absolute, traverses `..`, or contains `.git` | Reject it before filesystem mutation. |

## 5. Good / Base / Bad Cases

- Good: snapshot a tracked edit plus an untracked file; the resulting
  `snapshot_id` appears in `ToolResult.details` and `.git` remains intact.
- Base: every `run_shell` call receives a fresh snapshot ID even when the
  command text is read-only; no command classifier is involved.
- Bad: copying `.env` content into snapshot data, audit arguments, or Session
  JSONL violates this contract.
- Bad: calling a `LionTool.execute()` directly or injecting a conversation
  event bypasses the ToolRuntime/result path and is prohibited.

## 6. Tests Required

- `tests/tooling/test_workspace_snapshot.py`: ignored/sensitive metadata-only
  storage, `.git` preservation, newest-N GC, and retention-window GC.
- `tests/tooling/test_execution_audit.py`: exact event keys, append behavior,
  shell command serialization, and sensitive argument redaction.
- `tests/tooling/test_snapshot_runtime.py`: capability-triggered IDs for write
  and shell calls, and both components disabled.
- Before handoff: run focused tests, full `pytest`, unittest discovery,
  compileall, import-linter, and the repository quality baselines.

## 7. Wrong vs Correct

Wrong:

```python
if "rm -rf" in arguments["command"]:
    snapshot.create()
```

Correct:

```python
if tool.capabilities.mutates_workspace or tool.capabilities.executes_process:
    snapshot_id = snapshot.create()
```
