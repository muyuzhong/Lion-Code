# Tool Runtime Workspace Recovery

## 1. Scope / Trigger

This contract applies to the PR-S1 workspace recovery plane in
`lion_code/tooling/` and its Composition Root bindings. The trigger is a
cross-layer tool result contract: a mutating/process tool receives a workspace
snapshot ID, and a rollback result carries a model-visible notice through the
existing Core adapter path.

The plane contains only `WorkspaceSnapshot`, `ToolRuntime.rollback()`, and
`ExecutionAuditLog`. It does not add a permission system, risk classifier,
recovery manager, conversation injection channel, or a second tool execution
route.

## 2. Signatures

```python
SnapshotId = str

class WorkspaceSnapshot:
    def create(self) -> SnapshotId: ...
    def restore(self, snapshot_id: SnapshotId) -> RestoreResult: ...

class ToolRuntime:
    def rollback(self, snapshot_id: str, operation_summary: str) -> ToolResult: ...
```

`ToolBindings` owns the optional concrete services and independent switches:

```python
workspace_snapshot: WorkspaceSnapshot | None = None
audit_log: ExecutionAuditLog | None = None
enable_workspace_snapshot: bool = True
enable_audit: bool = True
```

The Composition Root creates defaults lazily and keeps snapshot storage and the
audit destination outside the workspace. The default snapshot store is
workspace-isolated; tests and hosts may inject both destinations.

## 3. Contracts

### Workspace and trigger contract

- `WorkspaceSnapshot.create()` captures tracked files, tracked absence
  markers, and non-ignored untracked files without changing the Git index or
  worktree. Git probes are read-only and scoped to the workspace path.
- Ignored files and `.env*`, `.credentials/`, and `.secrets/` paths receive
  only `exists`, `size`, and mtime metadata. Their contents never enter the
  snapshot tree. Snapshot directories are outside the workspace and use
  restrictive permissions where supported.
- `.git` is rejected by path validation and excluded from filesystem walks.
- `restore()` creates and returns a pre-restore snapshot before applying the
  target. The target and pre-restore IDs are protected from GC for the active
  operation. Restore covers workspace files only; it does not restore the Git
  index, commands, processes, databases, or external resources.
- GC keeps snapshots satisfying both the newest-N limit and the configured
  retention window; active operation IDs are protected exceptions.
- The pre-phase `WorkspaceSnapshotMiddleware` snapshots every tool whose
  `ToolCapabilities.mutates_workspace` or `.executes_process` is true. It does
  not inspect shell command text. The returned `ToolResult.details` contains
  `snapshot_id`.

### Rollback result contract

Successful rollback returns the exact content:

```text
以下操作结果已被撤销，请基于当前 workspace 重新判断
```

Its details contain `rollback.snapshot_id`,
`rollback.pre_restore_snapshot_id`, `rollback.operation_summary`, and
`rollback.restored`. The existing Core adapter forwards both content and
details; no conversation-runtime mutation is allowed.

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
  "result": "success | failed | rolled_back | blocked",
  "destination": null,
  "fingerprint_hit": null,
  "authorization_source": null,
  "sanitizer_hits": 0,
  "best_effort": null,
  "notes": []
}
```

PR-S1 fills execution results as `success` or `failed`, and rollback success
as `rolled_back`. PR-S2/S3/S5 fill the remaining columns: `sanitizer_hits`
from redaction, `destination`/`best_effort`/`fingerprint_hit` from the egress
guard, `blocked` + notes for egress blocks and budget-exceeded shutdowns,
and `session-grant` rows record the authorization snapshot at build time.

## 4. Validation & Error Matrix

| Condition | Required behavior |
|---|---|
| Snapshot creation fails while enabled | Return `ToolResult(is_error=True)` with no unsnapshotted tool execution; audit the failure when audit is enabled. |
| Tool raises after its pre-snapshot | Convert to the existing structured error boundary and retain `details.snapshot_id`. |
| Restore target is invalid or missing | Return `RestoreResult(restored=False)` and retain the pre-restore ID when creation succeeded. |
| Restore encounters a path conflict | Do not claim success; never delete `.git` or sensitive/ignored files. The pre-restore ID remains the recovery point. |
| Rollback succeeds | Return the exact notice and structured rollback details; append a `rolled_back` event. |
| Snapshot/audit switches are disabled | Do not create their services or storage; preserve ordinary ToolRuntime execution and result shape. |
| Snapshot path is absolute, traverses `..`, or contains `.git` | Reject it before filesystem mutation. |

## 5. Good / Base / Bad Cases

- Good: snapshot a tracked edit plus an untracked file, delete/change both,
  restore, and observe exact file contents with `.git` intact.
- Base: every `run_shell` call receives a fresh snapshot ID even when the
  command text is read-only; no command classifier is involved.
- Bad: an invalid restore or a failed materialization returns a structured
  failure with a usable pre-restore ID rather than silently continuing.
- Bad: copying `.env` content into snapshot data, audit arguments, or Session
  JSONL violates this contract.
- Bad: calling a `LionTool.execute()` directly or injecting a conversation
  event bypasses the ToolRuntime/result path and is prohibited.

## 6. Tests Required

- `tests/tooling/test_workspace_snapshot.py`: tracked/untracked restore,
  ignored/sensitive metadata-only storage, `.git` preservation, pre-restore
  recovery, newest-N GC, and retention-window GC.
- `tests/tooling/test_execution_audit.py`: exact event keys, append behavior,
  shell command serialization, and sensitive argument redaction.
- `tests/tooling/test_snapshot_runtime.py`: capability-triggered IDs for write
  and shell calls, rollback details/audit event, and both components disabled.
- `tests/integration/test_core_tool_runtime.py`: assert the exact rollback text
  in the Core `ToolResultMessage` on the next provider turn.
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

Wrong:

```python
conversation.emit("workspace rolled back")
```

Correct:

```python
return ToolResult(
    content="以下操作结果已被撤销，请基于当前 workspace 重新判断",
    details={"rollback": rollback_details},
)
```
