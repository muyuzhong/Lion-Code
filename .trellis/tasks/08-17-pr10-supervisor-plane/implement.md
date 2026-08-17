# PR10 Supervisor Plane — Implement

## Ordered checklist

1. Capture the pre-existing dirty file set and keep the PR9 branch baseline
   intact. Only stage PR10 production code, tests, active specs, README and
   Trellis task artifacts; never use `git add -A`.
2. Add the public `lion_code.supervisor` control-plane module:
   `Goal`, `SupervisorState`, `SupervisorResult`, `AgentPort`, `AgentFactory`,
   `RetryPolicy`, `Scheduler`, `CheckpointStore`, in-memory/JSON checkpoint
   stores, and the `Supervisor` state machine.
3. Keep the module independent of Agent implementations. Use only structural
   public result/event/session contracts; subscribe to Core `AgentEvent` values
   and never access Agent private fields or runtime containers.
4. Remove the stale Autonomy implementation and its private seams: old
   `autonomy.py`, `autonomy_runtime.py`, `domain_ports.py`, the side-query
   adapter/one-shot path if no remaining consumer exists, and the temporary
   `schedule_wakeup` tool. Delete old Agent-driven Autonomy tests rather than
   preserving skipped compatibility behavior; add focused Supervisor tests.
5. Add architecture tests for:
   - no Supervisor import/field/construction in Agent, Profiles or Composition;
   - Supervisor imports only public Core event contracts and no Agent private
     runtime;
   - strict checkpoint fields contain execution control only;
   - no removed project-state/dream/learning dependency in Supervisor.
6. Update existing boundary tests and active docs/specs:
   `four-layer-ownership.md`, `runtime-boundaries.md`,
   `directory-structure.md`, `error-handling.md`, `usage-ownership.md`,
   `tests/OWNERSHIP.md`, README and import-linter boundary expectations.
   Keep the application-owned foreground overflow event bridge unchanged unless
   a focused test proves the new public contract can replace it without
   widening scope.
7. Run focused tests after the new module and deletion slices. Resolve all
   scoped failures before interpreting full-suite noise.
8. Run static residual scans for removed modules, private Agent imports and
   forbidden durable fields; run `py_compile`, architecture tests, focused
   Supervisor tests, full runnable tests, import-linter and the repository
   quality gates from `.github/workflows/ci.yml`.
9. Review the final object graph: construct Minimal/Coding/Full profiles with
   no Supervisor import or state; construct Supervisor only through an injected
   factory; verify checkpoint JSON contains no Agent result/history fields.
10. Load `trellis-check` for the final full-scope quality review, fix findings,
    update the relevant Trellis spec if new boundary knowledge was discovered,
    then prepare the scoped Chinese commit plan. Do not push.

## Validation matrix

### Fast structural checks

```powershell
python -m py_compile <all scoped Python files>
rg -n --hidden --glob '!*.pyc' --glob '!.codegraph/**' --glob '!.trellis/tasks/**' `
  'AutonomyRuntime|ModelQuery|ProviderModelQuery|schedule_wakeup|_autonomy|MemoryRepository|SessionMemory|Dream|Learning|final_text|messages|transcript|embedding' `
  lion_code/supervisor.py lion_code/agent.py lion_code/composition tests/architecture
git diff --check
```

Interpret generic `memory` terms only in canonical `core/session/memory.py` by
the existing PR9 allowlist. The new Supervisor module must have no removed
feature import or durable result/history field.

### Focused behavior and architecture

```powershell
python -m pytest -q `
  tests/test_supervisor.py `
  tests/architecture/test_supervisor_plane.py `
  tests/architecture/test_bare_composition.py `
  tests/architecture/test_composition_profiles.py `
  tests/architecture/test_composition_root.py `
  tests/architecture/test_kernel_isolation.py `
  tests/architecture/test_runtime_boundaries.py `
  tests/application/test_coding_session_ports.py
```

The focused matrix must cover initial execution, public-event phase updates,
retry/backoff limits, checkpoint save/load/resume, factory/profile isolation,
terminal failure, cancellation, and strict durable-state rejection.

### Repository quality gates

```powershell
python -m unittest discover tests -p "test_*.py"
python -m pytest -q
python -m compileall -q lion_code tests scripts
lint-imports --no-cache
git diff --check
```

Then run the exact Ruff, Ruff format, mypy, Radon, vulture, coverage and
`check_quality_baseline.py` commands from `.github/workflows/ci.yml`, comparing
new failures against `docs/quality-baseline-2026-08.json`. Report unrelated
dirty-worktree baseline failures separately.

## Risky files and rollback points

- `lion_code/supervisor.py`: new state machine and durable boundary. Roll back
  before changing public Agent/Profile code if state semantics are unclear.
- `lion_code/agent.py`, `lion_code/composition/*`, Profiles: should be negative
  changes only; any new Supervisor field is a scope failure.
- `lion_code/application/session.py`: preserve the existing application event
  bridge and overflow retry ordering; do not silently change UI semantics.
- `tests/architecture/*` and active backend specs: keep executable boundary
  definitions synchronized with import-linter configuration.
- Checkpoint JSON implementation: atomic writes, path validation, strict field
  validation and no session JSONL coupling are mandatory.

## Review gates before `task.py start`

- [ ] `prd.md` has no unresolved product or scope decision.
- [ ] `design.md` and this `implement.md` reflect the evidence-backed plan.
- [ ] `research/` contains the two codebase research artifacts or an explicit
      reason the research was not needed.
- [ ] `implement.jsonl` and `check.jsonl` contain real spec/research entries.
- [ ] User explicitly approves the final planning summary.
