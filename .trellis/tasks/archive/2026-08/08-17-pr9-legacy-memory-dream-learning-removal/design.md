# PR9 Technical Design

## 1. Boundary decision

PR9 is a deletion and baseline-normalization change. The old project Memory graph is not re-homed into another layer. Dream and Learning are removed with their standalone runtime files because PR8 leaves them outside the product object graph but still present in production. The resulting runtime contains no Memory owner, Memory adapter, Memory placeholder, or Memory-specific lifecycle slot.

The canonical Session path is a separate concern:

```text
Core messages/events
    -> SessionLifecycle
    -> SessionRecorder -> JsonlSessionStorage -> <session-id>.jsonl
    -> SessionRepository -> SessionState replay
    -> ContextManager / ContextCompactor for provider context
```

`core/session/memory.py` remains part of this path because it defines persisted compaction/session entry data. It is not the deleted project Memory system.

## 2. Post-removal object graph

### FullProfile

```text
Agent facade
  -> FullProfile
  -> build_agent_composition(profile)
     -> foundation
        SessionIdentityState
        SessionRepository
        ExecutionControl
        UsageLedger / BudgetPolicy
        PermissionController / notices / confirmation
        ToolRegistry and Coding tools
        ContextManager
     -> ProviderManager
     -> Capability graph
        PlanRuntime -> PlanCapability
        SubagentFactory -> SubagentExecutor -> SubAgent capability
        SkillRuntime -> Skill capability
        extension_specs
     -> CapabilityRegistry
     -> CapabilityRuntime
     -> PromptComposer / ToolRuntime
     -> AgentRuntimeCoordinator
        LionAgentRuntime + SessionLifecycle + SessionRecorder
```

The resolved Full capability names are `skill`, `subagent`, `plan`, plus caller-supplied extension names. There is no `memory` name and no `session_memory_coordinator` field. MinimalProfile keeps an empty registry and no feature runtime. CodingProfile keeps Coding tools and optional Skill only.

### Generic retained seams

- `CapabilitySpec`: `tool_sources`, `prompt_layers`, `turn_participants`, `session_participants`, `resources`, and `requires`.
- `CapabilityRegistry`: registration, dependency ordering, extension aggregation, and resource closure only; it remains an aggregation mechanism, not a service locator.
- `CapabilityRuntime` / `CapabilityLifecycle`: generic turn/session lifecycle and close dispatch only.
- `ModelQuery` / `ProviderModelQuery`: retained because Autonomy runtime still imports the generic query contract and its unavailable-query error; no Memory-specific text-query adapter remains.
- `SessionRepository`, `SessionRecorder`, `SessionLifecycle`, `TranscriptView`, `ContextManager`, `ContextCompactor`, and Core Event Stream.
- Existing Plan prompt/session contributions, Skill tool binding, SubAgent tool binding, permission/notice ownership, and provider replacement seams.

## 3. Removal transformations

### Production modules and hooks

Delete the old Memory, Dream, and Learning files and remove all imports. In `lion_code/tools.py`, retain normal file-write behavior but remove the Auto Memory index rebuild callback. Remove `ProviderTextQueryService` and `TextQueryService` with `memory_runtime`; retain `model_query.py` because it has a non-legacy consumer. Remove `NoticeSinkAdapter` and the `AgentDependencies` project identity/context-loader seams if their only consumer is the deleted coordinator.

### Composition

`FullProfile` and builder selection lose Memory. `AgentComposition` loses `session_memory_coordinator`; `_SessionGraph` and the memory-only foundation fields disappear. `_build_session_graph` is deleted rather than retaining an empty graph or NullMemory. `AgentDependencies` loses `session_memory_repository`, `project_identity_resolver`, and `project_context_loader` because they only constructed the deleted project Memory path. `load_project_context_files()` remains in `prompt.py` for generic project instructions and UI prompt context.

### Facade and application

`Agent` removes the repository constructor argument, Memory private/public properties and project-identity delegation. `SessionMemoryPort`, its `CommandResult` fields, task parser, application dispatch method, and REPL/TUI dispatch branches are removed. The old task/session-memory/handoff/memory help entries disappear; unknown commands continue to use the generic existing path. No compatibility aliases are added.

### Capability SPI

The current evidence has one production ProjectionLayer implementation: `MemoryProjectionLayer`. Plan contributes a `PromptLayer`, not a ProjectionLayer. Therefore remove the entire projection slot from `capabilities/types.py`, `registry.py`, `runtime.py`, `capabilities/__init__.py`, and `AgentRuntimeCoordinator.prepare_core_context()`. The coordinator still calls `ContextManager.prepare()` and returns the prepared messages; canonical history and compaction semantics remain unchanged.

### Tests and architecture guards

Delete tests that exclusively prove old Memory/Dream/Learning behavior. Trim mixed Agent/Application/TUI/integration tests to keep canonical Session, context, Plan, Skill, SubAgent, provider, usage, and event assertions. Update FullProfile and zero-extension tests to assert the new graph. Add a focused production-only negative gate for removed files/symbols/adapters and ProjectionLayer slot names, with an explicit allowlist expectation for `core/session/memory.py`.

## 4. Documentation and metadata

Update `capability-spi.md`, `runtime-boundaries.md`, `four-layer-ownership.md`, `usage-ownership.md`, `tests/OWNERSHIP.md`, and the active `docs/project-brief.md` to describe the post-PR9 baseline. Remove obsolete Dream/Learning/Memory contracts and test paths. Remove deleted modules from package metadata and active import-linter/quality configuration. Historical Trellis archives and benchmark corpus snapshots are not treated as active contracts.

## 5. Compatibility, risks, and rollback

- This is intentionally breaking: old imports, constructor arguments, facade methods, and slash commands are deleted. No alias/fallback/migration is allowed.
- The main risk is confusing project Memory with canonical JSONL session entry code. The implementation must keep `core/session/memory.py`, `SessionRepository`, `SessionRecorder`, and compaction tests.
- The second risk is deleting generic `ModelQuery` because its name appears near old Memory/Dream code. Keep it and validate its Autonomy use.
- The third risk is leaving stale architecture specs or tests that reference deleted modules. Run residual scans over production, tests, active specs, and package metadata before the final commit.
- Rollback is by reverting the scoped PR9 commit(s); unrelated dirty Trellis/Codex infrastructure files remain untouched and are not included.
