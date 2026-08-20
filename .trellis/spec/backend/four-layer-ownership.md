# Four-Layer Ownership

This is the ownership map after the Runtime boundary PR. It documents executable
boundaries, not historical implementation or future Memory design.

## Ownership map

| Boundary | Current owners | Must not own |
| --- | --- | --- |
| Kernel | `core/`, `context/`, `tooling/`, `providers/`, `session_runtime/`, `permission_state.py`, `usage.py` | Product capabilities, Agent Runtime state, frontend state, project feature stores |
| Agent Runtime | `runtime/` (`agent.py`, `conversation.py`, `session.py`, `context.py`, `execution.py`, `session_identity.py`, `provider.py`) | Profile selection, a second history, service locator, deleted legacy graph, Composition/Application deps |
| Capability | `capabilities/` and its cohesive feature packages | Provider/session ownership, Product Adapter, Application/TUI, Memory/Dream/Learning replacements |
| Composition | `composition/`, `meta_agent.py` | Frontend behavior, Supervisor policy, retained runtime container, feature API leakage |
| Interfaces | `__init__.py`, `__main__.py`, `adapters/`, `application/`, `tui/` | Direct Kernel/Agent Runtime ownership, duplicate persistence, public legacy feature facade |
| Supervisor | `supervisor.py` | Agent content, usage, permissions, tools, Profile internals, canonical session writes |

`CapabilityRegistry` aggregates immutable contributions and closeable resources;
it is not a service locator. `ContextManager` and `ContextCompactor` remain
Kernel context policy and are the only generic provider-context preparation path.
Composition supplies `ContextLayer` implementations through a structural
callback; the Kernel never imports a concrete capability.

`AgentHarness` at `core/harness.py` is a Kernel stateful-loop wrapper, distinct
from the Agent Runtime. The `runtime/` package is the physical home of the Agent
Runtime layer: `AgentRuntime` (orchestration only), `ConversationRuntime`
(AgentHarness, canonical active messages, live provider/model, run capture,
retired provider close), `SessionRuntime` (session identity, repository,
recorder lifecycle, configuration-entry port), `ContextRuntime` (context
manager/compactor/limits cache, compaction state), `ExecutionControl`,
`SessionIdentityState`, and `ProviderController`/`ProviderState`. AgentRuntime
and ProviderController never reference each other in either direction. The
Composition Root creates `ProviderConfigurationProjection` before the Runtime
graph so provider-read callbacks close over a controller-free projection;
ProviderController synchronizes that projection after successful state
transitions while retaining exclusive provider-configuration write ownership.
The object graph is constructed in one topological pass with no deferred
binding. Full product bootstrap also belongs to `composition/`; adapters only
implement product-facing delegation.

## Current composition

Composition inputs are three orthogonal axes: `Profile` (WHAT TO BUILD —
product preset), `AgentConfig` (HOW IT RUNS — value-type runtime settings), and
`RuntimeBindings` (WITH WHAT — concrete implementation bindings grouped as
`ProviderBindings` / `SessionBindings` / `ToolBindings` / `InteractionBindings`).
They meet only in `build_agent_composition`.

`MinimalProfile` constructs an empty CapabilityRegistry unless caller
`extension_specs` are supplied. `CodingProfile` adds Coding tools and Coding
Harness policy plus AgentState/GitStatus ContextLayers. `FullProfile` adds
those layers together with Plan, SubAgent, and Skill built-in Capabilities.
Caller `extension_specs` are orthogonal to the Product preset: every Profile
forwards them into the CapabilityRegistry. Every Profile produces a
feature-neutral `MetaAgent`; capability services remain private to the graph.
No Profile creates or names a Memory, Dream, Learning, Null, Deprecated, Legacy,
or fallback object.

## Canonical session ownership

`SessionRepository` replays JSONL and `SessionRecorder` appends Core events;
`SessionRuntime` is their single owner and coordinates
new/load/restore/compact/close transitions. Session restore is explicit
cross-owner orchestration: `SessionRuntime.load` returns an immutable
`SessionRestoreState`, the facade commands
`ProviderController.restore_configuration`, then `AgentRuntime.restore(state)`
replays the messages. The canonical compaction entry model at
`core/session/memory.py` is retained. It must not be confused with the removed
project-level Memory files or repositories.

Application code consumes semantic ports from `application/ports.py`. It owns
frontend event bridging and overflow retry policy; it does not inspect Runtime
queues or cache Core runtime objects. TUI code reaches the runtime through the
application session.

## Deleted boundary

PR9 removed the old project Memory package and coordinator, Dream modules and
adapter, Learning runtime, Memory-only provider text query, Memory file-write
hook, project Memory facade/application ports, and the Memory-only per-request
capability projection slot. The generic ContextLayer slot is intentionally
retained for ephemeral prepared-context projections; no compatibility alias or
placeholder remains.

The Supervisor consumes only the public Agent event/result/session contracts.
Goal lifecycle, scheduler, retry/recovery and execution-control checkpoints are
owned by `supervisor.py`; Provider request retry, UsageLedger/BudgetPolicy,
canonical session replay and Application overflow retry remain with their
existing owners. Skill, Plan, SubAgent, Provider, permission, Event Stream and
context compaction remain active ownership contracts.

## Architecture tests

`tests/architecture/test_legacy_memory_removal.py` checks exact removed modules
and the current zero-symbol manifest, while its enduring legacy scanner allows a
future Capability-owned Memory shape and the canonical `core/session/memory.py`.
Other architecture tests cover import direction
(`_boundaries.py` + import-linter; Kernel keeps zero Agent Runtime imports),
composition profiles, zero-extension, capability lifecycle, session persistence,
provider ownership, application ports, ContextLayer transientness, and
TUI/Runtime direction. The runtime ownership test also checks that Composition
passes a completed ContextLayer snapshot without a reverse
ContextManager-to-CapabilityRegistry edge.
