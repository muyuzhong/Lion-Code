# PR-S1 Workspace Snapshot & Rollback Event

## Goal

Add a bounded, optional recovery plane to Lion's Tool Runtime so workspace file
changes made by coding tools can be restored after an incorrect operation. The
plane consists only of workspace snapshots, rollback results, and append-only
execution events; it must not become a permission, risk, recovery-manager, or
conversation-runtime subsystem.

The user-visible value is that a failed or destructive tool operation can be
undone at the workspace filesystem boundary, while the next model turn receives
an explicit rollback explanation and can re-evaluate the current workspace.

## Confirmed repository facts

- `lion_code/tooling/runtime.py::ToolRuntime.execute` is the single registered
  tool execution path and already owns the pre/post middleware chain.
- `LionTool.capabilities` already distinguishes workspace mutation and process
  execution (`mutates_workspace`, `executes_process`); built-in `write_file`,
  `edit_file`, and `run_shell` use those declarations.
- `lion_code/tooling/types.py::ToolResult` already carries structured `details`
  and `is_error` without requiring a Core message-model change.
- `lion_code/adapters/tool_adapter.py` forwards `ToolResult.details` into the
  provider-neutral result, and `lion_code/core/loop.py` puts both result text
  and details into the canonical `ToolResultMessage`; provider adapters expose
  result text to the next model request. A rollback notice therefore belongs in
  result content, with structured rollback data in `details`.
- Composition constructs the Tool Runtime in
  `lion_code/composition/agent_builder.py`; `ToolBindings` is the existing
  concrete infrastructure seam for tool execution dependencies.
- The requested Kernel/Runtime/Core files are not implementation targets:
  `meta_agent.py`, `runtime/conversation.py`, `runtime/session.py`,
  `runtime/context.py`, and `capabilities/` remain unchanged.

## Requirements

### R1. Workspace snapshot contract

Add `lion_code/tooling/snapshot.py` with the minimal public contract:

```python
class WorkspaceSnapshot:
    def create(self) -> SnapshotId: ...
    def restore(self, snapshot_id: SnapshotId) -> RestoreResult: ...
```

Snapshots cover the workspace filesystem state represented by tracked files,
tracked deletions, and non-ignored untracked files. The implementation may use
read-only Git metadata probes plus an equivalent external tree capture, but it
must not mutate the repository index or worktree while creating a snapshot.

### R2. Ignored and sensitive paths

- Ignored files are never copied as a full snapshot.
- `.env*`, `.credentials/`, `.secrets/`, and equivalent sensitive path matches
  receive metadata only: existence, modification time, and size.
- Sensitive contents must not enter the snapshot store or the execution audit
  through file-write arguments.
- Snapshot storage is outside the workspace and its directories/files use
  restrictive local permissions where the platform supports them.

### R3. Restore and protection semantics

- Snapshot/restore operations never write to, delete from, or clean `.git`.
- `restore()` first creates a pre-restore snapshot and returns its ID in the
  `RestoreResult`, so a restore operation can itself be undone.
- Restore only promises workspace filesystem state. It does not promise command,
  external-resource, database, Git-index, or process rollback.
- Expected snapshot and restore failures surface as structured results at the
  Tool Runtime boundary; they do not escape into a second execution loop.

### R4. Automatic triggers

Before every tool whose capabilities declare `mutates_workspace` or
`executes_process`, Tool Runtime middleware unconditionally creates a snapshot.
This includes all write/edit/delete tools and every shell tool call; it does not
inspect command text for indirect writes. The generated `snapshot_id` is
included in the returned `ToolResult.details`.

### R5. Rollback event

Expose a Tool Runtime rollback operation that invokes `WorkspaceSnapshot.restore`
without adding a conversation injection channel or changing
`runtime/conversation.py`. A successful rollback result contains:

- `details.rollback.snapshot_id`
- `details.rollback.pre_restore_snapshot_id`
- `details.rollback.operation_summary`
- `details.rollback.restored`
- model-visible text: `以下操作结果已被撤销，请基于当前 workspace 重新判断`

The operation summary is supplied by the caller and is not inferred by a risk
classifier. A failed rollback remains a structured error and reports the
pre-restore snapshot ID when available.

### R6. Append-only execution audit

Add one fixed `ExecutionEvent` schema and an append-only `ExecutionAuditLog`.
Every tool execution records the schema below; fields not owned by PR-S1 remain
`null` and `notes` remains a list:

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

Rollback emits a corresponding `rolled_back` event on success. Audit output is
explicitly injectable and append-only; it is not Session JSONL and is never
written through SessionRecorder. Sensitive file-write argument values are
redacted before serialization.

### R7. Safe complete disablement

`ToolBindings` must allow workspace snapshots and audit to be independently
disabled. When both are disabled, Tool Runtime retains its existing direct
execution behavior, no snapshot or audit storage is created, and a normal Agent
task completes without any new result fields being required.

### R8. Architecture boundary

All production changes stay in `lion_code/tooling/` and the Composition Root's
binding/wiring seam. Do not modify `lion_code/meta_agent.py`,
`lion_code/runtime/conversation.py`, `lion_code/runtime/session.py`,
`lion_code/runtime/context.py`, or `lion_code/capabilities/`. Tool calls
continue through `ToolRuntime`; no direct tool execution or parallel rollback
path may be introduced.

## Acceptance Criteria

- [ ] A tracked file is written, changed destructively, restored from a
  snapshot, and has the exact snapshot content afterward.
- [ ] A new non-ignored untracked file is present at snapshot time, deleted,
  and restored with its original content.
- [ ] Every shell execution through `ToolRuntime` returns a distinct
  `details.snapshot_id` before/for that call; repeated shell calls create
  repeated snapshot IDs.
- [ ] `restore()` returns a pre-restore snapshot ID, and restoring that ID after
  an intentionally incorrect restore recovers the prior workspace state.
- [ ] A rollback result contains the required rollback details and the exact
  model-visible notice; the notice survives the Core adapter loop into the next
  provider-visible tool result without modifying conversation runtime code.
- [ ] Creating more than the configured maximum leaves the newest N snapshots
  and removes the oldest snapshot.
- [ ] A composition with both snapshot and audit components disabled completes a
  normal tool/Agent task without creating snapshot or audit artifacts.
- [ ] Focused tests, architecture tests, compile checks, `git diff --check`, and
  the repository's full test/quality gates pass without new baseline violations.

## Out of scope

- Permission prompts, permission modes, authorization policy, risk scoring,
  fingerprint classification, or a Recovery Manager subsystem.
- Command/process rollback, network or external-resource rollback, database
  rollback, Git-index rollback, or conversation/session-history rollback.
- Full backup or restoration of ignored/sensitive secret contents.
- Changes to Core message models, provider payload schemas, conversation/session/
  context runtime owners, or capability SPI.

## Risks and deferred items

- Snapshot creation performs filesystem and Git metadata I/O before mutating or
  process tools. If that infrastructure operation fails while enabled, the tool
  call returns a structured snapshot error instead of executing unsnapshotted;
  disabling the component remains the explicit escape hatch.
- Snapshots are filesystem captures, not atomic transactions against a process
  that is concurrently mutating the workspace. The implementation serializes
  snapshot/restore operations within one `WorkspaceSnapshot` instance but does
  not promise external writer coordination.
- Audit uses a dedicated non-session JSON-lines file with a configurable path;
  its destination, authorization, and fingerprint fields remain reserved for
  later PRs.

## Blocking open questions

None. Product scope, boundary, retention behavior, and acceptance behavior are
specified by the request and repository evidence.
