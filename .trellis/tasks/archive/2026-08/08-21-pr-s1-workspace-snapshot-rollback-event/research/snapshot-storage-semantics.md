# Snapshot Storage and Restore Semantics

## Selected approach

Use an external per-workspace snapshot directory, configurable for tests and
defaulting under the user's Lion data directory. Do not use `git stash`, index
mutation, `git clean`, or a worktree reset during snapshot creation or restore.

Each snapshot stores a manifest plus copies of non-sensitive workspace files.
The manifest records the tracked path universe from the Git `HEAD` tree and
current index, current non-ignored untracked paths, file kind/mode, and absence
markers. Git probes are read-only. For a non-Git root, the implementation falls
back to a filesystem walk excluding `.git`; there is no tracked/ignored
classification in that fallback.

Restore removes current non-ignored, non-sensitive paths that are absent from
the snapshot and materializes the snapshot's stored files. Ignored and
sensitive paths are left in place and are represented only by metadata. All
resolved paths are checked to stay below the workspace root and `.git` is
explicitly rejected before any filesystem operation.

## Why this satisfies the hard behavior

- Tracked modifications, staged/unstaged tracked files, tracked deletions, and
  non-ignored untracked files are represented by the captured tree, so restore
  does not depend on the current Git index state.
- The snapshot store is outside the workspace, so its files cannot become
  workspace untracked files and restore never needs to clean the repository.
- Sensitive contents never enter the store. Only `exists`, `mtime`, and `size`
  metadata are written for matching paths.
- `restore()` creates a new snapshot before applying the target snapshot. The
  returned pre-restore ID is protected from GC for the duration of the call,
  allowing a failed or incorrect restore to be undone.
- GC keeps snapshots within both the newest configured N and the retention
  window. Snapshots protected by an active create/restore operation are kept
  for that operation. Tests can use a small N and a temporary store to verify
  the behavior deterministically.

## Operational decisions

- Snapshot IDs are opaque random strings and are the only identifier exposed to
  ToolResult/audit consumers.
- Snapshot directories and audit parent directories are created with restrictive
  permissions where supported; individual snapshot data/manifest files are not
  world-readable by design.
- Snapshot creation or restore failures are returned as structured Tool Runtime
  errors. The normal operation is not classified by command contents or risk.
