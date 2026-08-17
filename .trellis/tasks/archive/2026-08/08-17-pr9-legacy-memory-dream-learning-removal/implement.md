# PR9 Implementation Plan

Implementation starts only after the final planning summary is explicitly approved and `task.py start` changes the task to `in_progress`.

## Ordered checklist

1. Reconfirm `HEAD == origin/master == 26d0dd4`, capture the dirty-worktree file set, and create a scoped file list. Never stage or restore unrelated Trellis/Codex changes.
2. Remove the old production modules and production hooks: Memory files/package, Dream files/adapter, Learning runtime, `tools.py` Memory index callback, old text-query adapter, and other now-unused imports/metadata.
3. Simplify Composition/Profile: remove `_CAP_MEMORY`, Memory-only fields/helpers/dependencies/adapters, update FullProfile docs/selection, and ensure Minimal/Coding/Full object graphs construct without any Memory object.
4. Remove Agent facade and Application/TUI/REPL Memory command surfaces, including the old task/session-memory/handoff ports and dispatch paths. Keep generic unknown-command behavior and all canonical Session operations.
5. Remove ProjectionLayer end to end: protocol, spec field, registry aggregation, lifecycle/runtime method, coordinator call, exports, tests, and active specs. Keep ContextManager projection/compaction behavior.
6. Delete legacy-only tests and trim mixed tests without weakening retained Session/history, compaction, provider, usage, event, Skill, Plan, or SubAgent coverage.
7. Add/update architecture guards for exact removed symbols/modules/adapters and the absent ProjectionLayer slot. Verify the guard explicitly does not ban generic `memory` or `core/session/memory.py`.
8. Update active architecture/product/test ownership docs, package metadata, import-linter expectations, and quality-baseline entries for removed files. Do not edit historical Trellis archives or unrelated benchmark snapshots unless a current test consumes them as a contract.
9. Run focused tests after each deletion slice, then compile, full tests, import-linter, residual scans, `git diff --check`, and scoped quality checks. Separate baseline failures caused by pre-existing dirty files from PR9 results.
10. Review the final object graph and acceptance matrix, update Trellis spec if needed, commit the scoped change with a Chinese commit message, and report the removed graph/retained seams/future boundary.

## Suggested validation matrix

### Fast structural checks

```powershell
python -m compileall -q lion_code tests scripts
rg -n --hidden --glob '!*.pyc' --glob '!.codegraph/**' --glob '!.trellis/tasks/**' `
  'SessionMemoryCoordinator|SessionMemoryRepository|MemoryCapability|DreamCoordinator|LearningRuntime|_CAP_MEMORY|ProjectionLayer|projection_layers|ProviderTextQueryService|TextQueryService' `
  lion_code tests .trellis/spec docs pyproject.toml
git diff --check
```

The residual scan is interpreted by scope: exact legacy symbols must be absent from production and active contracts; generic `memory` text and `core/session/memory.py` are allowed where they describe canonical session entries.

### Focused behavior

```powershell
python -m pytest -q `
  tests/architecture/test_legacy_memory_removal.py `
  tests/architecture/test_composition_profiles.py `
  tests/architecture/test_composition_root.py `
  tests/architecture/test_bare_composition.py `
  tests/capabilities/test_capability_registry.py `
  tests/capabilities/test_capability_runtime.py `
  tests/integration/test_agent_core_runtime.py `
  tests/integration/test_application_coding_session.py `
  tests/session_runtime `
  tests/test_model_query.py `
  tests/test_prompt.py
```

### Final repository checks

```powershell
python -m pytest -q
python -m compileall -q lion_code tests scripts
lint-imports --no-cache
python -m ruff check <scoped production and test files> --output-format=json
python scripts/check_quality_baseline.py ...
git diff --stat
git diff --check
```

Use the repository's committed CI command forms for format, mypy, coverage, Radon, and vulture. Do not claim a dirty-worktree baseline failure is caused by PR9.

## Risky files / rollback points

- `lion_code/composition/agent_builder.py`, `lion_code/agent.py`, and `lion_code/agent_runtime.py`: object graph and runtime context boundary. Roll back before changing tests if Session or Provider behavior regresses.
- `lion_code/application/commands.py`, `application/session.py`, `application/ports.py`, `__main__.py`, and `tui/app.py`: command-surface deletion. Preserve generic command parsing and frontend event ownership.
- `lion_code/capabilities/types.py`, `registry.py`, `runtime.py`, and capability tests: ProjectionLayer slot deletion. Verify zero-extension and Plan prompt behavior immediately.
- `tests/integration/test_agent_core_runtime.py`: remove Memory-specific assertions while retaining restore/compaction/usage/provider coverage.
- Active specs and package metadata: update only references to deleted current behavior; leave historical archives/dirty infrastructure untouched.
