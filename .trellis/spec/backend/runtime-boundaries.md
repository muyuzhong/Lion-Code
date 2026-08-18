# Runtime and Layer Boundaries

This contract describes the final post-PR11 runtime. The repository has one canonical
Core history and one JSONL session writer. Project Memory, Dream, and Learning
are removed; this document must not describe replacement objects or adapters.

## Composition root

`AgentConfig` is a frozen value object containing user/runtime settings.
`AgentDependencies` contains injected repositories, factories, callbacks, and
test seams. Neither owns mutable runtime state.

`build_agent_composition(profile)` is the one-shot Composition Root. It creates
state owners, Provider and permission ports, tools, ContextManager, selected
capabilities, Core runtime, and the coordinator. `AgentComposition` is the
one-shot runtime graph. `build_profile_agent(profile)` wraps every selected graph
in the same feature-neutral `MetaAgent`. The internal `Agent` product host subclasses
that facade only to retain Application/CLI-specific operations; it is not part
of the package-root public API. No facade retains a builder, CapabilityRegistry,
project-Memory repository, or legacy command delegate.

Profiles select the graph:

- `MinimalProfile`: MetaAgent, caller tools, neutral prompt, and an empty
  CapabilityRegistry.
- `CodingProfile`: MetaAgent plus Coding tools and Coding Harness policy, with
  an empty CapabilityRegistry.
- `FullProfile`: Coding tools plus Plan, SubAgent, default Skill, and supplied
  extension specs, still behind MetaAgent.

No profile creates a Memory, Dream, Learning, Null, Deprecated, Legacy, or
fallback object.

## State ownership

Every mutable runtime state has one owner. Consumers receive views and send
commands through narrow ports:

- `SessionIdentityState` owns the session id and start time.
- `ExecutionControl` owns cancellation transitions.
- `PermissionController` owns permission mode and confirmations.
- `ProviderManager` owns provider configuration and thinking state.
- `UsageLedger` and `BudgetPolicy` own usage and budget decisions.
- `PlanRuntime` owns Plan state.
- `SessionRepository` replays JSONL and `SessionRecorder` appends events.
- `ContextManager` and `ContextCompactor` prepare and compact provider context.
- `AgentRuntimeCoordinator` owns Core run orchestration and event capture.

Observers and frontends must not cache writable mirrors or access Core/Harness
containers directly.

## Canonical session and context path

```text
Core messages/events
  -> SessionLifecycle
  -> SessionRecorder -> JsonlSessionStorage -> <session-id>.jsonl
  -> SessionRepository -> SessionState replay
  -> ContextManager / ContextCompactor -> Provider request
```

`lion_code/core/session/memory.py` remains the JSONL compaction-entry module.
Its name is historical session terminology, not a project Memory subsystem.
Canonical history, restore, compaction, legacy JSON read-only migration, and
Event Stream behavior remain in scope and must keep their tests.

## Application and frontend ports

`lion_code.application.ports` owns the protocol consumed by
`LionCodingSession`. The application owns event bridging, settled-event timing,
session commands, provider settings, and the one-at-most-one context-overflow
compact/retry policy. Runtime owns primitive prompt, continuation, cancellation,
and compaction operations.

The active slash surface contains session/history, provider, Plan, cost,
compaction, theme, thinking, quit, and Skill commands. Former project-state and
memory-specific command paths are absent. Unknown commands retain the generic
unknown-command behavior.

The TUI imports application contracts only. The REPL may render terminal output
but must not own session persistence or a second command dispatcher.

## Retained runtime seams

- `CapabilityRegistry`, `CapabilityRuntime`, `Plan`, `Skill`, and `SubAgent`.
- The public `AgentEvent`, result and session-reference contract consumed by
  `supervisor.py`.
- Provider replacement, usage recording, permission confirmation, ContextManager
  preparation, ContextCompactor summaries, and Core Event Stream.

These are narrow ports, not compatibility aliases. `Supervisor` must not import
Agent/Harness implementations or hold a second session-history writer. Its
checkpoint contains execution-control fields only and is separate from the
canonical session JSONL path.

## Verification obligations

Architecture tests must assert that removed production modules and exact legacy
symbols are absent. A current-architecture manifest keeps the specifically
removed Memory Capability symbols at zero; the enduring legacy scanner still
allows a future Capability-owned Memory implementation and
`core/session/memory.py`, without permitting the old ports, modules or coupling
to return. Run focused composition, Capability, session, provider,
application, and prompt tests before the full suite, then run compile, import
linting, residual scans, and the repository quality gates.
