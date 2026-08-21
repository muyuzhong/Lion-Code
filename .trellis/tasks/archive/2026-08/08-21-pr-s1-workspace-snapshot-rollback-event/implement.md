# PR-S1 Implementation Plan

## Ordered checklist

1. Add `tooling/snapshot.py` with typed contracts, external manifest/tree
   storage, Git/filesystem path enumeration, sensitive metadata-only handling,
   `.git` guards, pre-restore snapshots, and configurable GC.
2. Add `tooling/audit.py` with the one `ExecutionEvent` schema, append-only
   writer, stable argument serialization, sensitive redaction, and result
   mapping.
3. Extend `ToolContext` and `ToolBindings` with optional recovery dependencies
   and independent switches; keep defaults lazy and storage outside the
   workspace.
4. Add `WorkspaceSnapshotMiddleware` to the existing Tool Runtime pipeline and
   wire `AuditMiddleware` to the append-only writer from the Composition Root.
   Snapshot only capability-marked mutation/process tools; do not inspect shell
   command text or add a risk classifier.
5. Add `ToolRuntime.rollback()` returning a `ToolResult` whose content carries
   the exact rollback notice and whose details carry target/pre-restore IDs and
   operation summary. Keep all model synchronization in the returned result.
6. Export the new tooling contracts and preserve the no-component path when
   both switches are disabled.
7. Add focused tests under `tests/tooling/` and an integration test under
   `tests/integration/` for all seven requested acceptance cases, including
   provider-visible rollback content and no forbidden runtime-file edits.
8. Run the focused tests, compile checks, architecture checks, full unittest/
   pytest suite, and the repository quality gates against the existing baseline.
9. Perform final diff inspection for `.git` safety, secret-content leakage,
   exact audit schema, and only task-owned staging.

## Validation matrix

| Area | Validation |
| --- | --- |
| Snapshot tree | `python -m pytest -q tests/tooling/test_workspace_snapshot.py` |
| Audit schema | `python -m pytest -q tests/tooling/test_execution_audit.py` |
| Runtime trigger/rollback | `python -m pytest -q tests/tooling/test_runtime.py tests/tooling/test_builtin_tools.py` |
| Model-visible result | `python -m pytest -q tests/integration/test_core_tool_runtime.py` |
| Architecture | `python -m pytest -q tests/architecture/test_tool_routing.py tests/architecture/test_composition_profiles.py tests/architecture/test_runtime_boundaries.py` |
| Syntax | `python -m compileall -q lion_code tests` |
| Full suite | `python -m pytest -q` |
| Diff hygiene | `git diff --check` and scoped `git diff --stat` |
| CI quality | Ruff/mypy/radon/vulture commands from `.github/workflows/ci.yml`, each compared with `docs/quality-baseline-2026-08.json` |

## Risky files and rollback points

- `lion_code/tooling/snapshot.py`: filesystem deletion/copy logic; validate all
  targets stay below the workspace root and never equal/descend from `.git`.
- `lion_code/tooling/middleware.py`: middleware order; retain cancellation,
  hook, permission, freshness, result, and audit ordering semantics.
- `lion_code/composition/agent_builder.py`: object graph wiring; keep optional
  components outside Profiles and Runtime owners.
- `lion_code/tooling/types.py` / adapter path: preserve existing result fields
  and Core mapping; no Core wire-model changes unless tests prove necessary.

If implementation requires a forbidden file or a second execution route, stop
and return to design rather than widening scope. If snapshot restore tests fail,
first isolate path enumeration, then restore materialization, then GC; do not
weaken the `.git` or sensitive-path gates.

## Review gates before `task.py start`

- `prd.md`, `design.md`, and this `implement.md` have been read top to bottom.
- Requirements and acceptance criteria have no unresolved product decision.
- Research records current execution/result boundaries and storage semantics.
- `implement.jsonl` and `check.jsonl` contain real backend spec entries if the
  task uses sub-agent dispatch.
- The latest planning summary has been presented to the user and explicitly
  approved. Only then run `task.py start`.

