# Implementation Plan: Capability PromptLayer 与 SessionParticipant 运行时接入

## 1. Baseline and context

- [x] Confirm `master`/base commit, active task and dirty paths; preserve existing
      unrelated `.claude`/Trellis edits.
- [x] Run the focused baseline for Plan, Capability migration/registry, runtime,
      session and architecture tests; record failures separately from this task.
- [x] Read the capability SPI, runtime-boundary and quality specs before editing.

Rollback point: planning-only; no product code changes yet.

## 2. Extract PromptComposer

- [x] Add `PromptComposer` beside the existing prompt builders with stable base,
      dynamic context replacement and a callable PromptLayer provider.
- [x] Wire `Agent` to construct one Composer from the existing static/dynamic builders
      and pass `composer.get_system` to `AgentRuntimeCoordinator`/Core.
- [x] Remove Agent `_base_system_prompt`/`_system_prompt` prompt mirrors and make Dream
      dynamic-context refresh update only Composer-owned dynamic context.
- [x] Add exact ordering, per-call layer read, empty-fragment, custom-system and
      no-history tests.

Focused validation:

```powershell
python -m pytest -q tests/core/test_dynamic_configuration.py tests/test_prompt.py
```

Rollback point: revert Composer wiring while keeping the existing prompt builders.

## 3. Complete PlanCapability

- [x] Remove prompt fields, host prompt mutation and `refresh_prompt()` from
      `PlanRuntime`; keep PlanState/permission/approval/path/pending-reset behavior.
- [x] Add `PlanPromptLayer` using only `PlanView`, preserving the current instruction
      text and plan path.
- [x] Add `PlanSessionParticipant` for new/restore transitions.
- [x] Extend the existing `create_plan_capability` spec with exactly those layer and
      participant contributions; keep direct PlanRuntime ToolSource closures.
- [x] Rewrite Plan runtime tests around PlanState + Composer projection and preserve all
      approval/error/path/context-reset cases.

Focused validation:

```powershell
python -m pytest -q tests/test_plan_runtime.py tests/capabilities/test_capability_migration.py
```

Rollback point: Plan tools remain the existing single capability source and can be
restored independently of lifecycle dispatcher wiring.

## 4. Add generic Capability lifecycle adapter

- [x] Add `CapabilityLifecycle` port and a minimal `CapabilityRuntime` backed only by
      CapabilityRegistry.
- [x] Dispatch before/after turn and new/restore session participants in Registry order;
      close Registry resources once with existing error semantics.
- [x] Update AgentRuntimeCoordinator to receive and use the port instead of Agent hook
      methods; remove corresponding Agent methods.
- [x] Update SessionLifecycle to receive the same port, remove Plan-specific calls, and
      preserve core/session/memory/MCP ownership and ordering.
- [x] Add explicit ordering tests for early exits, errors, session transitions and
      repeated close.

Focused validation:

```powershell
python -m pytest -q tests/capabilities tests/runtime/test_agent_runtime.py tests/tooling/test_agent_runtime.py
```

Rollback point: dispatcher is a single seam; coordinator/session call sites can revert
without changing any Capability implementation.

## 5. Full SPI lifecycle test capability

- [x] Add a test-only Capability implementing ToolSource, PromptLayer, TurnParticipant,
      SessionParticipant and AsyncCloseable.
- [x] Verify tool contribution, prompt projection, before/core/after order,
      new/restore callback order and one-time resource closure.
- [x] Add Plan integration coverage for first request after new/restore reading fresh
      PromptComposer output and for direct Plan tool execution.

Focused validation:

```powershell
python -m pytest -q tests/capabilities tests/integration/test_agent_core_runtime.py tests/memory_runtime/test_core_integration.py
```

## 6. Architecture and spec review

- [x] Add AST/source guards for the requested PlanRuntime, SessionLifecycle, Agent,
      PromptComposer, PromptLayer and SessionParticipant boundaries.
- [x] Update `capability-spi.md` and `runtime-boundaries.md` to describe the now-live
      PromptLayer/SessionParticipant and generic lifecycle port; keep docs truthful and
      do not mention AgentBuilder as implemented.
- [x] Run a scoped search for removed prompt fields, Agent hook forwarding and direct
      SessionLifecycle Plan knowledge.

Focused validation:

```powershell
python -m pytest -q tests/architecture/test_runtime_boundaries.py tests/capabilities
lint-imports --no-cache
```

## 7. Full quality gates and handoff

- [x] `python -m pytest -q`
- [x] `python -m compileall -q lion_code tests`
- [x] `lint-imports --no-cache`
- [x] `git diff --check -- <task-owned paths>`
- [x] `python ./.trellis/scripts/task.py validate 08-13-capability-prompt-session-runtime`
- [x] Run final full-scope Trellis quality check; fix verified findings and repeat until
      green.
- [x] Inspect exact staged paths; keep unrelated dirty files unstaged.
- [x] Update spec via `trellis-update-spec`, record journal, then commit with a Chinese
      description after the required commit-plan confirmation.

Final report must cover: prompt mutable-state -> projection change; Plan knowledge removed
from SessionLifecycle; final lifecycle call chain; PlanCapability slots; complete quality
gate outputs; and explicit statement that AgentBuilder was not started.
