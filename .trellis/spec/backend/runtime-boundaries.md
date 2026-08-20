# Runtime and Layer Boundaries

This contract describes the current runtime. The repository has one canonical
Core history and one JSONL session writer. Project Memory, Dream, and Learning
are removed; this document must not describe replacement objects or adapters.

## Physical layers

The package is split into physical boundaries visible in the directory tree:

- **Kernel** — `core/`, `context/`, `tooling/`, `providers/`, `session_runtime/`,
  `permission_state.py`, `usage.py`.  Kernel is independently understandable and
  never imports the Agent Runtime, Composition, or Application.
- **Agent Runtime** — `runtime/` owns the single-session Agent lifecycle through
  four owners plus state owners: `agent.py` (AgentRuntime — operation
  orchestration only), `conversation.py` (ConversationRuntime — AgentHarness,
  canonical active messages, live provider/model, run capture, retired provider
  close), `session.py` (SessionRuntime — session identity, repository, recorder
  lifecycle, provider configuration-entry port), `context.py` (ContextRuntime —
  context manager/compactor, model limits cache, compaction state),
  `execution.py` (ExecutionControl), `session_identity.py`
  (SessionIdentityState), and `provider.py` (ProviderController /
  ProviderState).  The Runtime may use Kernel, Context and Tooling, but never
  Composition, Application or TUI.
- **Capability** — `capabilities/`, including the cohesive `plan/`, `skill/`,
  and `subagent/` feature packages. Capabilities never import the Agent
  engine, Application or TUI.
- **Composition** — `composition/` and `meta_agent.py`; the Composition Root
  knows the Agent Runtime and wires the graph.
- **Supervisor** — `supervisor.py`, consuming only the public Agent event /
  result / session contracts.
- **Interfaces** — package root public API, `__main__.py`, `adapters/`,
  `application/`, and `tui/`. Product-specific frontend delegation lives in
  `CodingSessionBackendAdapter`; `MetaAgent` remains feature-neutral.

`AgentHarness` at `core/harness.py` is a Kernel stateful-loop wrapper; it is not
the Agent Runtime.

## Composition root

The composition inputs are three orthogonal axes:

- `Profile` — WHAT TO BUILD: an immutable composition preset (caller tools,
  system prompt, `extension_specs`). It never carries config, bindings,
  provider, repository, backend, or presentation callbacks.
- `AgentConfig` — HOW IT RUNS: a frozen value object of user-visible runtime
  settings only; it holds no mutable runtime objects.
- `RuntimeBindings` — WITH WHAT: concrete implementation bindings grouped by
  responsibility (`ProviderBindings`, `SessionBindings`, `ToolBindings`,
  `InteractionBindings`). It is wiring, not a runtime-state owner.

`build_agent_composition(profile, config=config, bindings=bindings)` is the
one-shot Composition Root and the only place where the three axes meet. It
creates state owners, Provider and permission ports, tools, ContextManager,
selected capabilities, the four Runtime owners, and the ProviderController —
in one topologically sorted pass with no deferred post-construction binding:

```text
foundation → ContextRuntime → ConversationRuntime → SessionRuntime
          → AgentRuntime → ProviderController
```

`AgentComposition` is the one-shot layered graph; it does not retain the
profile, config, or bindings, and never returns a flat bag of everything:

```text
AgentComposition
├── runtime         agent / conversation / session / context /
│                   provider_controller / usage / budget
├── capabilities    registry / runtime / plan / skill / subagent
├── tooling         registry / runtime / context / permission_policy /
│                   prompt_composer
└── interaction     notices / confirmation / status_sink
```

`build_profile_agent(profile, config=config, bindings=bindings)`
wraps every selected graph in the same feature-neutral `MetaAgent`.
`CodingSessionBackendAdapter` adds FullProfile product operations through
composition and delegation; it is not a `MetaAgent` subtype. No facade retains
a builder, CapabilityRegistry, project-Memory repository, or legacy command
delegate.

Profiles select the graph:

- `MinimalProfile`: MetaAgent, caller tools, neutral prompt, and an empty
  CapabilityRegistry.
- `CodingProfile`: MetaAgent plus Coding tools and Coding Harness policy, with
  an empty CapabilityRegistry.
- `FullProfile`: Coding tools plus Plan, SubAgent, default Skill, and supplied
  extension specs, still behind MetaAgent.

`command_backend` is a `ToolBindings` entry (defaulting to the local backend);
confirm callbacks, renderer factories, and print callbacks are
`InteractionBindings` entries. Neither pollutes any Profile.

No profile creates a Memory, Dream, Learning, Null, Deprecated, Legacy, or
fallback object.

## State ownership

Every mutable runtime state has one owner. Consumers receive views and send
commands through narrow ports:

- `SessionIdentityState` owns the session id and start time.
- `ExecutionControl` owns cancellation transitions.
- `PermissionController` owns permission mode and confirmations.
- `ProviderController` owns provider configuration and thinking state; it
  commands ConversationRuntime (`replace_provider` / `set_model` /
  `retire_provider`), ContextRuntime (`replace_context_compactor` /
  `invalidate_model_limit_cache`), and SessionRuntime
  (`record_configuration_change`). It is never referenced by AgentRuntime in
  either direction.
- `UsageLedger` and `BudgetPolicy` own usage and budget decisions.
- `PlanRuntime` owns Plan state.
- `SessionRuntime` owns session lifecycle and the recorder; `SessionRepository`
  replays JSONL and `SessionRecorder` appends events. Provider configuration
  changes are recorded through the SessionRuntime recorder port.
- `ContextRuntime` owns the context manager, the provider-derived compactor,
  the model-limits cache, `effective_window`, and all compaction decision
  state (compaction flag, in-flight compaction task).
- `ConversationRuntime` owns the AgentHarness, the canonical active messages,
  the live provider/model, run output capture, and retired-provider close.
- `AgentRuntime` owns run orchestration order and stop-reason projection only;
  it holds no provider, context, or session mutable state.

Runtime must not query `ProviderController` for the current model, provider,
or context limits: live model/provider come from ConversationRuntime and
limits from ContextRuntime. Provider, context, scheduler, and configuration
recording ownership is wired directly during composition; deferred binding
ports are not part of the runtime graph.

Observers and frontends must not cache writable mirrors or access Core/Harness
containers directly.

## Canonical session and context path

```text
Core messages/events
  -> SessionRuntime (recorder ownership)
  -> SessionRecorder -> JsonlSessionStorage -> <session-id>.jsonl
  -> SessionRuntime.load -> immutable SessionRestoreState
  -> facade: ProviderController.restore_configuration + AgentRuntime.restore
  -> ContextRuntime.prepare/compact -> Provider request
```

`AgentRuntime` operations compose the owners in a fixed order, e.g. chat:
`SessionRuntime.ensure_ready` (after `ConversationRuntime.flush` and
`ContextRuntime.resolve_model_limits`) → `ContextRuntime` compaction decision
→ `ConversationRuntime.prompt` → stop-reason projection. Session restore is
the explicit facade orchestration above; SessionRuntime never calls back into
the ProviderController.

`lion_code/core/session/memory.py` remains the JSONL compaction-entry module.
Its name is historical session terminology, not a project Memory subsystem.
Canonical history, restore, compaction, legacy JSON read-only migration, and
Event Stream behavior remain in scope and must keep their tests.

## Application and frontend ports

`lion_code.application.ports` owns the protocol consumed by
`LionCodingSession`. The application owns event bridging, settled-event timing,
session commands, provider settings, and the one-at-most-one context-overflow
compact/retry policy. The Agent Runtime owns primitive prompt, continuation,
cancellation, and compaction operations.

The active slash surface contains session/history, provider, Plan, cost,
compaction, theme, thinking, quit, and Skill commands. Former project-state and
memory-specific command paths are absent. Unknown commands retain the generic
unknown-command behavior.

The TUI imports application contracts only. The REPL may render terminal output
but must not own session persistence or a second command dispatcher.

## Product adapter contract (PR4)

### 1. Scope / Trigger

This contract applies when a product frontend needs FullProfile operations that
are not part of the generic Agent facade. The frontend boundary is
`CodingSessionBackend`; product behavior stays in
`CodingSessionBackendAdapter`, while generic conversation and runtime behavior
stays in `MetaAgent`.

### 2. Signatures

The public construction seams are:

```python
build_profile_agent(
    profile: Profile,
    *,
    config: AgentConfig,
    bindings: RuntimeBindings,
) -> MetaAgent

build_full_coding_backend(
    *,
    permission_mode: PermissionMode = "default",
    model: str = "claude-opus-4-6",
    session_repository: SessionRepository | None = None,
    tool_registry: ToolRegistry | None = None,
    ...,
) -> CodingSessionBackendAdapter
```

`CodingSessionBackendAdapter` structurally implements `CodingSessionBackend`
and receives a `MetaAgent`, `PlanRuntime`, interaction controllers, and the
session repository it delegates to.

### 3. Contracts

- `build_profile_agent` returns the same `MetaAgent` facade shape for Minimal,
  Coding, and Full profiles.
- `build_full_coding_backend` constructs `FullProfile → AgentComposition →
  MetaAgent → CodingSessionBackendAdapter`.
- Generic methods (`prompt`, `continue_`, `steer`, `follow_up`, cancellation,
  compaction, provider views, and usage) delegate to `MetaAgent`.
- Product methods (session enumeration/legacy migration, Plan approval,
  terminal output, notices, confirmation, and cost presentation) are owned by
  the adapter and its injected controllers.
- `MetaAgent` must not expose product-specific methods or import adapters.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Minimal/Coding/Full profile construction | Exact `MetaAgent` result with the same Runtime owner tuple |
| Full product construction | `CodingSessionBackendAdapter` satisfying `CodingSessionBackend` |
| Adapter used as a `MetaAgent` subtype | Forbidden by MRO/architecture tests |
| Product method added to `MetaAgent` | Forbidden by the MetaAgent surface guard |
| Old `lion_code.agent` or root feature module imported | Forbidden by residual and architecture guards |

### 5. Good / Base / Bad Cases

- Good: use `build_profile_agent` for generic runtime consumers and
  `build_full_coding_backend` for the application/TUI product path.
- Base: pass injected repository, registry, and confirmation callbacks through
  the factory so the adapter delegates to the same composition graph.
- Bad: subclass `MetaAgent`, copy product methods into it, or add a compatibility
  alias for a removed root module.

### 6. Tests Required

- `tests/architecture/test_product_adapter.py`: public `Agent` removal, adapter
  protocol/MRO, generic SPI isolation, feature tree, and profile runtime shape.
- `tests/adapters/test_coding_session_backend.py`: delegation, legacy session
  migration, callbacks, terminal output, and cost projection.
- `tests/integration/test_meta_agent.py`: exact feature-neutral MetaAgent
  surface, including generic queue/compaction/provider projections.
- `tests/architecture/_boundaries.py` and import-linter: adapter direction and
  Supervisor isolation.

### 7. Wrong vs Correct

Wrong:

```python
class CodingSessionBackendAdapter(MetaAgent):
    # Product methods become part of every generic Agent facade.
    ...
```

Correct:

```python
class CodingSessionBackendAdapter:
    def __init__(self, *, agent: MetaAgent, ...):
        self._agent = agent
```

Composition is the extension seam: generic profiles remain interchangeable and
the product adapter can be removed without changing Runtime ownership.

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
to return. Import-direction contracts live in `tests/architecture/_boundaries.py`
and the import-linter config in `pyproject.toml`; they keep Kernel independent
of the Agent Runtime (`runtime/`) and keep Runtime free of Composition/Application
dependencies. `tests/architecture/test_runtime_ownership.py` additionally proves
the PR3 object graph: AgentRuntime and ProviderController never reference each
other, the Deferred wiring symbols stay deleted, each Runtime owner's mutable
state stays single-owner, and the runtime package keeps no Application/TUI
imports. Run focused composition, Capability, session, provider,
application, and Runtime tests before the full suite, then run compile, import
linting, residual scans, and the repository quality gates.
