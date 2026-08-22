# Implementation Plan

This plan is not activated. Run it only after the user approves the final planning summary and `task.py start` moves the task to `in_progress`.

## Slice 1 — Restore authoritative project instruction injection

Responsibility: make a default fresh Full product session see the project files Lion already knows how to load.

- [ ] Add focused tests proving `build_full_coding_backend` dynamic context includes root-to-cwd `CLAUDE.md` / `AGENTS.md` content once and preserves ordering.
- [ ] Update `_full_dynamic_context_builder` to append `load_claude_md()` to the existing environment/Git context, dropping blank content.
- [ ] Preserve current custom-system-prompt opt-out behavior and avoid a second loader/cache.
- [ ] Update the relevant active backend spec in the same commit after behavior is verified.
- [ ] Commit with a Chinese description; stage only slice-owned paths.

Rollback point: revert this slice; no durable data was created or migrated.

## Slice 2 — Add the Project Lessons Capability end to end

Responsibility: provide local evidence-backed recall/write/forget without rebuilding the removed Memory graph.

- [ ] Add `capabilities/project_lessons/repository.py` with strict `ProjectLesson` / document validation, deterministic search, exact-key upsert/delete, and atomic JSON replacement.
- [ ] Add `capabilities/project_lessons/capability.py` with one PromptLayer and the three model-facing tools.
- [ ] Mark recall read-only/concurrency-safe; mark remember/forget `requires_confirmation=True`; use bounded, structured ToolResults.
- [ ] Construct the Capability from existing `ProjectIdentity` / `project_storage_dir` and select it only for FullProfile.
- [ ] Keep the repository and tools private to the Capability: no Agent/Runtime/Application/TUI fields or ports.
- [ ] Add unit tests for missing/corrupt/wrong-root files, unknown fields, duplicate keys, path normalization, stable ranking, result budget, atomic replacement, real deletion, and confirmation metadata.
- [ ] Add composition/architecture tests proving Full contains `project_lessons`, Coding/Minimal remain unchanged, Runtime cannot reach a new feature owner, legacy symbols remain absent, and Session/Compaction schemas are unchanged.
- [ ] Update `runtime-boundaries.md`, `four-layer-ownership.md`, tests ownership, and any public product description only after the implementation passes.
- [ ] Commit with a Chinese description; stage only slice-owned paths and keep `after1.tmp` untouched.

Rollback point: unregister/revert the Capability. Preserve `~/.lion-code/projects/<key>/lessons.json` as recoverable local user data unless the user separately authorizes deletion.

## Focused verification

```powershell
$env:GIT_CEILING_DIRECTORIES = 'C:\Users\暮羽中'
python -m pytest -q tests/test_prompt.py tests/test_project_identity.py
python -m pytest -q tests/capabilities/test_project_lessons.py
python -m pytest -q tests/architecture/test_composition_profiles.py tests/architecture/test_legacy_memory_removal.py
python -m compileall -q lion_code tests
git diff --check
```

Add or adjust the exact focused file list to match implementation-owned tests; do not run unrelated format rewrites.

## Full quality gate before push

- [ ] Run the full test suite and distinguish existing Windows/baseline noise from scoped regressions.
- [ ] Run the CI-equivalent Ruff, format, mypy, Radon, Vulture, coverage, import-linter, and architecture gates exactly as defined by `.github/workflows/ci.yml`, comparing against `docs/quality-baseline-2026-08.json`.
- [ ] Run `python ./.trellis/scripts/task.py validate .trellis/tasks/08-22-memory-system-design-convergence`.
- [ ] Confirm `git diff --stat` contains only real task changes and no line-ending rewrite.
- [ ] Confirm every new production line is covered and the reachable object graph preserves Runtime/Plan/Session boundaries.

## Review gates

1. Review Slice 1 as a standalone behavior correction.
2. Review Slice 2 against the design's explicit deletion/defer table; reject any Hook, background LLM call, SQLite/index, compatibility layer, new Runtime owner, facade API, CLI/TUI, or scheduled maintenance added without a new measured requirement.
3. Keep each PR below the repository's commit/file thresholds and merge in dependency order.
