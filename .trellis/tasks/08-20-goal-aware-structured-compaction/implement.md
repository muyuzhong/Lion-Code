# Goal-Aware Structured Compaction — Implementation Plan

## Execution constraints

- Do not use an implementation subagent; the main session edits and verifies the code.
- A check subagent may be used during Phase 2.2 after the main implementation is complete.
- Preserve the unrelated untracked `after1.tmp`; stage only task-owned source, tests, specs and
  Trellis artifacts.
- Keep one coherent responsibility in this task and use a Chinese commit description when the
  final commit plan is approved.

## Ordered checklist

1. **Contract and template**
   - Add immutable `CompactionRequest` and the structural PlanView protocol/helper in
     `lion_code/context/compaction.py`.
   - Replace the `ContextCompactor.summarize()` input with the request type.
   - Add one `COMPACTION_PROMPT_TEMPLATE` containing the nine fixed headings, objective and
     recent-context framing, and explicit Findings/Verification evidence rules.
   - Update `ProviderContextCompactor` to clone history, render recent context as background,
     interpolate the objective marker, and preserve provider error/cancellation behavior.
   - Export the new contract/template from `lion_code/context/__init__.py`.

2. **Request assembly and wiring**
   - Extend `ContextRuntime.summarize()` with keyword-only recent context/objective inputs.
   - Assemble `CompactionRequest` at the ContextRuntime boundary immediately before the existing
     asyncio task is created; do not add mutable state.
   - Pass `foundation.plan` as a read-only structural view from the Composition Root.
   - Pass `user_message` and `messages[boundary:]` through the existing AgentRuntime compaction
     call without changing boundary, policy, event, cancellation or recorder semantics.

3. **Focused tests**
   - Update `tests/context/test_compaction.py` for the new request contract, objective marker,
     recent-context rendering, all headings, evidence requirements, canonical deep-copy behavior,
     and provider errors.
   - Add ContextRuntime request-assembly coverage, including explicit objective, user-message
     fallback, active PlanView content, inactive/missing Plan and empty objective marker.
   - Update integration compactor fakes and automatic 85% compaction assertions to prove the
     current objective and retained context are sent while the summary is still written through
     CompactionEntry.
   - Keep and extend policy/projection tests for the recent-three and latest-read-file guards;
     assert canonical history is unchanged after projection and compaction.

4. **Validation and review**
   - Run the focused context/session/runtime/integration tests first.
   - Run `python -m compileall -q lion_code tests scripts`, full `python -m pytest -q`,
     `git diff --check`, import-linter, Ruff check/format, mypy, radon/vulture and branch/
     changed-lines coverage using the commands in `.github/workflows/ci.yml` and the current
     quality baseline.
   - Run architecture ownership tests and inspect the final diff for prohibited Kernel,
     AgentHarness, policy, SessionEntry, or broad Runtime changes.
   - If check finds issues, fix them in the main session and rerun the affected gates; use the
     permitted check subagent only for review assistance, not implementation.

5. **Finish**
   - Decide whether this PR produced a durable spec convention; if yes, update the matching
     `.trellis/spec/backend` document before commit.
   - Recheck `git status --porcelain`, stage only known task paths, present the one-shot commit
     plan, and commit only after user confirmation. Do not push or create a PR unless separately
     authorized.

## Validation command set

```powershell
python -m compileall -q lion_code tests scripts
python -m pytest -q tests/context/test_compaction.py tests/context/test_policy.py tests/context/test_context_layer.py tests/session_runtime/test_recorder.py tests/integration/test_agent_core_runtime.py tests/integration/test_meta_agent.py
python -m pytest -q
python -m ruff check lion_code tests scripts --output-format=json > ruff.json
python scripts/check_quality_baseline.py ruff-check ruff.json --status 1 --baseline docs/quality-baseline-2026-08.json
python -m ruff format --check lion_code tests scripts
python -m mypy lion_code --platform win32 -O json > mypy.jsonl 2>&1
lint-imports --no-cache
python -m radon cc lion_code -j > radon-cc.json
python -m coverage run --branch -m pytest -q -p no:cacheprovider
python -m coverage json -o coverage.json
git diff --check
```

The CI workflow's baseline comparison commands remain authoritative when local exit status is
non-zero because of pre-existing fingerprints. Report scoped regressions separately from dirty
worktree or repository baseline noise.
