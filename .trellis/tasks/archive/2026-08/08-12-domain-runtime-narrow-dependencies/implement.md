# Implementation Plan: Narrow Domain Runtime Agent Dependencies

## 1. Establish narrow shared contracts

- [x] Add the minimal shared TranscriptView, NoticeSink, ConversationRunner, and
  ModelQuery protocols.
- [x] Add the live Provider-backed ModelQuery adapter beside the existing
  provider-neutral one-shot completion helper.
- [x] Split the existing Memory read-only message source into TranscriptView plus
  the separately injected Memory query dependency; remove the obsolete combined
  source contract.
- [x] Add focused contract/query tests, including typed role-preserving messages,
  live provider/model lookup, and unavailable-query behavior.

Rollback point: the new ports and adapter are unused and can be removed without
touching domain behavior.

## 2. Migrate Autonomy and Learning

- [x] Delete AutonomyHost and inject every dependency explicitly.
- [x] Replace dictionary evaluator messages with typed AgentMessage values and
  move all transcript/query/notice/cancellation/tool/confirm accesses to their
  named dependency.
- [x] Delete LearningRuntimeHost and inject transcript/query/cwd explicitly.
- [x] Update direct and Agent-level Goal, loop, Auto classifier, and Learning tests.
- [x] Add AST/import guards for Agent/Core Runtime/private runtime independence.

Focused validation:

```powershell
python -m pytest -q tests/test_autonomy.py tests/test_autonomy_flow.py tests/test_learning.py
python -m pytest -q tests/architecture/test_runtime_boundaries.py
```

Rollback point: shared ports remain, but both runtimes can be reverted together
without touching Memory or Dream.

## 3. Migrate Session Memory and Dream

- [x] Make the ProviderManager Memory sink bindable after coordinator composition
  without changing replacement ordering or failure atomicity.
- [x] Replace SessionMemoryHost with explicit identity/repository/transcript/
  cancellation/permission/project/notice/query/Dream/status/refresh dependencies.
- [x] Replace coordinator `Any` fields and properties with concrete types.
- [x] Define typed DreamAgentRunner, DreamAgentFactory, SessionMemoryView, and child
  usage-recorder ports.
- [x] Make DreamCoordinator consume only repository, identity, memory view,
  factory, usage recorder, and pure data.
- [x] Move the concrete restricted child and factory to the Agent composition
  layer; keep pure read-root validation reusable from Dream domain code.
- [x] Preserve and integrate the pre-existing deferred Capability metadata
  assertion in `tests/test_dream.py`.
- [x] Update Session Memory read/update/semantic extraction and all Dream success,
  error, validation, conflict, rollback, and security tests.
- [x] Add architecture guards for no Agent import/argument/field and no forbidden
  Memory dependencies.

Focused validation:

```powershell
python -m pytest -q tests/test_session_memory.py tests/test_session_memory_coordinator.py
python -m pytest -q tests/memory_runtime tests/test_dream.py
python -m pytest -q tests/architecture/test_runtime_boundaries.py
```

Rollback point: revert the Session Memory/Dream composition slice together; the
unchanged plan parser and atomic apply functions remain independently testable.

## 4. Migrate SubagentFactory when still local

- [x] Add typed ChildAgentConfig and explicit registry/environment/config/
  permission constructor parameters.
- [x] Delete SubagentFactoryHost and obsolete Agent child-host helpers.
- [x] Preserve ordinary/Skill tool selection, environment child views, provider
  configuration inheritance, and plan/auto/default permission behavior.
- [x] Update capability/subagent factory tests and architecture guards.

Focused validation:

```powershell
python -m pytest -q tests/capabilities/test_capability_migration.py tests/tooling/test_capability_runtimes.py
python -m pytest -q tests/architecture/test_tool_routing.py tests/architecture/test_runtime_boundaries.py
```

Rollback point: SubagentFactory is an independent adjacent constructor migration
and can be reverted without reverting the other domains.

## 5. Integration and architecture review

- [x] Search the scoped production files for Agent/Core Runtime imports,
  `_core_runtime`, Agent private reads, forbidden Any annotations, and `agent` or
  `host` constructor parameters.
- [x] Verify no RuntimeContext/AgentServices/DomainContext or equivalent service
  locator was introduced.
- [x] Measure and record before/after counts of migrated `Any` annotations and
  private runtime/Agent references for the final report.
- [x] Run the full behavior matrix requested by the PRD.
- [x] Review the complete diff against the pre-existing dirty worktree and keep
  unrelated Trellis/template changes unstaged.

## 6. Full quality gates

- [x] `python -m pytest -q`
- [x] `python -m compileall -q lion_code tests scripts`
- [x] Run the committed repository quality-baseline wrapper(s) discovered from
  CI/docs for changed-scope lint, formatting, typing, complexity, dead code, and
  coverage checks.
- [x] `lint-imports --no-cache`
- [x] `git diff --check -- <task-owned paths>`
- [x] `python ./.trellis/scripts/task.py validate 08-12-domain-runtime-narrow-dependencies`
- [x] Run `trellis-check`; resolve every verified regression.

## 7. Documentation, commit, and final report

- [x] Update the runtime-boundary spec to describe the implemented narrow ports,
  composition owner, and Dream adapter boundary.
- [ ] Record the session journal through Trellis finish workflow.
- [ ] Stage only task-owned source, tests, spec, task, and journal files.
- [ ] Commit with a Chinese description.
- [x] Report old wide dependencies, new narrow objects, measured removals, Dream
  security preservation, and every quality-gate result.
- [x] Stop after this task; do not start PromptComposer, SessionParticipant,
  AgentBuilder, or any later stage.
