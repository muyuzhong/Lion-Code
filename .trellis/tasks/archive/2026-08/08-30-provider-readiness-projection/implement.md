# 实施计划：Provider readiness 单一投影

## Execution model

- Planning completed with `gpt-5.6-sol / high` research.
- Implementation worker must use `gpt-5.6-luna / max`.
- Only this one improvement is in scope: unify Provider readiness and expose one stable REST blocker code.
- Do not modify unrelated code, do not add compatibility fallbacks, and do not commit until the parent workflow authorizes the commit phase.

## Ordered checklist

1. Read `prd.md`, `design.md`, the research file, and all manifest-referenced specs; confirm the current branch and dirty paths are preserved.
2. Use CodeGraph before editing `provider.py`, composition ports/builder, `agent.py`, application/session ports, server status models/routes, and Desktop status decoding. Search for every existing `api_configured` reader before changing the source.
3. Add the frozen `ProviderReadiness` value and single blocker-code rule inside the existing Provider projection; keep explicit concrete Provider readiness and current key/base URL semantics.
4. Replace duplicate bool formulas with projection delegation across Runtime identity, `ProviderController`, `MetaAgent`, Application/session and backend ports. Read one snapshot at Runtime and REST status boundaries.
5. Add the required nullable `provider_blocker_code` to the server status contract and strict Desktop status decoder. Keep TUI and `WorkspaceShell` behavior unchanged.
6. Add/update focused tests for the full readiness truth table, transaction failure preservation, Runtime no-request behavior, REST bool/code invariants, strict Desktop decoding, and architecture ownership.
7. Review the diff for forbidden scope: no new Manager/Registry/Resolver/Catalog, no Core message/WS/JSONL change, no UI behavior change, no credential leakage.
8. Run targeted validation first. Because this is a cross-layer public status contract, run the project-required quality gate only after the focused checks pass and classify any baseline/environment failures separately.
9. Run `git diff --check`, `git status --short --untracked-files=all`, and inspect the final diff. Keep `.trellis/workspace/zhangcx/journal-1.md`, existing `agents/notes/`, and unrelated changes untouched.

## Target files

Expected production scope, subject to CodeGraph confirmation:

- `lion_code/runtime/provider.py`
- `lion_code/composition/ports.py`
- `lion_code/composition/agent_builder.py`
- `lion_code/runtime/agent.py`
- `lion_code/meta_agent.py`
- `lion_code/adapters/coding_session_backend.py`
- `lion_code/application/ports.py`
- `lion_code/application/session.py`
- `lion_code/server/models.py`
- `lion_code/server/app.py`
- `desktop/src/renderer/src/backend.ts`

Expected test scope:

- `tests/test_provider_controller.py`
- `tests/runtime/test_agent_runtime.py` or the current focused AgentRuntime test file
- `tests/integration/test_meta_agent.py`
- `tests/server/test_server_api.py`
- `tests/architecture/test_runtime_ownership.py`
- relevant application fake/port tests
- `desktop/tests/renderer/assistantRuntime.test.ts`
- `desktop/tests/renderer/WorkspaceShell.test.tsx` or the current status decoder test file

Do not modify `lion_code/tui/app.py`, `desktop/src/renderer/src/WorkspaceShell.tsx`, `lion_code/core/messages.py`, `lion_code/server/bridge.py`, or `desktop/src/shared/chat.ts` unless a focused test proves the strict contract cannot be completed otherwise; any such expansion requires updating this plan before editing.

## Focused validation

```powershell
python -m pytest -q tests/test_provider_controller.py tests/runtime/test_agent_runtime.py tests/integration/test_meta_agent.py tests/server/test_server_api.py tests/architecture/test_runtime_ownership.py
Set-Location desktop
npm test -- --run tests/renderer/assistantRuntime.test.ts tests/renderer/WorkspaceShell.test.tsx
npm run typecheck
Set-Location ..
python -m compileall -q lion_code tests
git diff --check
```

If the actual test paths differ, use the repository's current targeted equivalents and record the substitution in the final task report. Do not call real Provider APIs.

## Review gates before `task.py start`

- [ ] `prd.md` has no unresolved product/scope/risk decision.
- [ ] `design.md` defines ownership, data flow, compatibility, failure behavior and rollback.
- [ ] `implement.md` lists an ordered bounded implementation and focused checks.
- [ ] `implement.jsonl` and `check.jsonl` contain real spec/research entries, not `_example` rows.
- [ ] Latest planning summary has been presented to the user and explicitly approved.
