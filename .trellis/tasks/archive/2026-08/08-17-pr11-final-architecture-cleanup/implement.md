# PR11 Final Architecture Cleanup — Implement

## Ordered checklist

1. Preserve the unrelated dirty Trellis/tooling paths and stage only PR11 files.
2. Delete `ProductFacadeKind`, `SkillComposition` and facade fields from Profile,
   selection and composition results; remove Coding optional Skill construction.
3. Add `build_profile_agent(Profile) -> MetaAgent`; route Minimal/Coding builders
   through it and export the final Profile/factory API at package root.
4. Make internal Full `Agent` reuse/subclass `MetaAgent` for the generic surface,
   retaining only `CodingSessionBackend` controls and existing test seams.
5. Update Profile/object-graph tests for Minimal/Coding/Full -> MetaAgent and add
   Full external CapabilitySpec smoke coverage.
6. Add Test C for Plan/Skill/SubAgent/third-party incremental registration and
   every single omission, including zero-extension runtime lifecycle.
7. Refactor the PR9 scanner into legacy-path/coupling detection that allows a
   synthetic future Memory Capability while rejecting the old architecture.
8. Add exact MetaAgent/package public API guards and Supervisor factory/Profile
   isolation assertions.
9. Add Composition and MetaAgent dependency contracts to `_boundaries.py` and
   `pyproject.toml`; update index-based architecture helpers.
10. Update README, ownership docs and backend specs to the final PR11 graph and
    remove PR9/optional-Coding-Skill/dual-facade wording.
11. Run py_compile, focused Profile/Capability/Supervisor/session tests, all
    architecture tests, full pytest, compileall, import-linter, Ruff/mypy/radon/
    vulture/coverage baseline gates and `git diff --check`; fix scoped findings.
12. Run final Trellis check, synchronize specs/baseline only when required, stage
    only scoped paths and create Chinese work commit(s).

## Validation matrix

### Fast/focused

```powershell
python -m py_compile lion_code/meta_agent.py lion_code/agent.py `
  lion_code/composition/profiles.py lion_code/composition/agent_builder.py
python -m pytest -q `
  tests/integration/test_meta_agent.py `
  tests/architecture/test_composition_profiles.py `
  tests/architecture/test_bare_composition.py `
  tests/architecture/test_composition_root.py `
  tests/architecture/test_legacy_memory_removal.py `
  tests/architecture/test_supervisor_plane.py `
  tests/capabilities/test_capability_registry.py `
  tests/capabilities/test_capability_runtime.py
python -m pytest -q tests/session_runtime tests/context `
  tests/integration/test_agent_core_runtime.py
```

### Full quality gates

```powershell
python -m pytest -q
python -m compileall -q lion_code tests scripts
lint-imports --no-cache
git diff --check
```

Run the exact Ruff check/format, mypy, Radon, vulture and coverage baseline
commands from `.github/workflows/ci.yml`. New fingerprints are defects; line
drift updates the committed baseline only when the scoped source move caused it.

## Risky files and rollback points

- `lion_code/agent.py` / `meta_agent.py`: preserve dynamic patch seams and the
  application `CodingSessionBackend` contract while deduplicating common API.
- `composition/agent_builder.py`: preserve one-shot owner construction and keep
  Radon below new D/E/F fingerprints.
- `tests/architecture/test_legacy_memory_removal.py`: avoid both an ineffective
  broad keyword scan and a gate that blocks future Memory Capability work.
- `_boundaries.py` / `pyproject.toml`: representations must stay byte-for-byte
  equivalent through `test_import_linter_config_matches_boundaries`.
- session runtime files are not intended edit targets; any required change sends
  implementation back to planning review.

## Planning gate

- Requirements and local baseline are fully resolved by repository evidence and
  the user's explicit scope.
- No product decision remains open.
- The user explicitly instructed planning to proceed directly to implementation,
  so no additional approval/question gate is required for this task.
