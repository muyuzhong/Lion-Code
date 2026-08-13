# Design: Narrow Domain Runtime Agent Dependencies

## Boundary Strategy

Use one small low-level ports module for the four shared structural contracts and
keep concrete adapters in existing composition/provider locations. This adds one
intentional contract module while removing the host protocols and the concrete
Dream child from the domain module; it does not create a context bag or service
registry.

```text
Agent composition root
  ├─ LionAgentRuntime ───────────────> TranscriptView
  ├─ AgentRuntimeCoordinator ────────> ConversationRunner
  ├─ Provider-backed adapter ────────> ModelQuery
  ├─ callback adapter ───────────────> NoticeSink
  ├─ ExecutionControl.cancellation ──> CancellationView
  ├─ PermissionController ───────────> PermissionView
  ├─ restricted child adapter ───────> DreamAgentFactory
  └─ explicit concrete tool/config dependencies

Domain consumers
  ├─ AutonomyRuntime
  ├─ LearningRuntime
  ├─ SessionMemoryCoordinator
  ├─ DreamCoordinator
  └─ SubagentFactory
```

The concrete runtime objects may structurally implement the narrow protocols,
but domain constructors never receive `Agent` itself.

## Shared Ports

Create a low-level module with only:

- `TranscriptView.messages: tuple[AgentMessage, ...]`
- `NoticeSink.emit(message, role="info")`
- `ConversationRunner.chat(prompt)`
- `ModelQuery.complete_text(...)`
- `ModelQuery.complete_messages(...)`

`ModelQuery.complete_messages` accepts typed Core `AgentMessage` values so Goal
evaluation keeps its role framing without an untyped dictionary protocol.
`complete_text` is the single-user-message convenience used by classification
and Learning. A Provider-backed concrete adapter lives with the existing one-shot
Provider helper and resolves the live provider/model through callables, so
ProviderManager replacement cannot leave Autonomy or Learning on a stale
provider. The adapter checks API readiness internally and raises a dedicated
unavailable error; readiness is not added to the domain protocol.

## Composition Order

`Agent.__init__` remains the sole composition root. Construction changes only as
needed to make real narrow objects available:

1. Build permission, execution, usage, tool environment, Plan, and registry.
2. Build `SubagentFactory` from registry/environment/config/permission and then
   register capabilities.
3. Build ToolRuntime, ProviderManager, and AgentRuntimeCoordinator as today.
4. Bind a deferred Memory query sink to the coordinator after the coordinator is
   constructed; ProviderManager continues to own replacement-time Memory query
   refresh.
5. Build the live Provider-backed `ModelQuery`, notice adapter, restricted Dream
   factory, DreamCoordinator, and SessionMemoryCoordinator.
6. Build AutonomyRuntime and LearningRuntime from the narrow runtime/query views.

The existing AgentRuntimeCoordinator `MemoryTurnHost` delegation is not expanded
in this task. It becomes usable only after Agent construction completes, exactly
as today. PromptComposer, SessionParticipant, and AgentBuilder remain untouched.

## Autonomy Runtime

Replace the `_host` field with named fields:

- `_conversation: ConversationRunner`
- `_transcript: TranscriptView`
- `_query: ModelQuery`
- `_notices: NoticeSink`
- `_cancellation: CancellationView`
- `_tool_registry: ToolRegistry`
- `_confirm: ConfirmCallback | None`
- the existing shared `_usage` and `_budget`

Goal transcript extraction reads only `_transcript.messages`. Goal evaluation uses
typed messages through `complete_messages`. Auto classification uses
`complete_text`, while registry checks and the temporary wakeup tool use the
concrete stable `ToolRegistry`. All cancellation checks read the supplied token.

## Learning Runtime

Replace `_host` with `_transcript`, `_query`, and frozen `_cwd`. Serialize the
canonical transcript snapshot exactly once and make one `complete_messages` call
containing a typed user message. Skill validation and creation remain unchanged.

## Session Memory Coordinator

The coordinator receives each dependency independently:

- identity and the matching concrete repository;
- transcript and cancellation read views;
- permission read view;
- typed `ProjectContextFile` loader callable;
- notice sink;
- current `TextQueryService` for Memory recall/semantic extraction;
- `DreamRunner`;
- immutable sub-agent flag;
- existing narrow subagent-status callback and dynamic-context refresh callback.

`MemoryCoordinator` and project context collections receive concrete types, not
`Any`. Semantic extraction uses the injected current query instead of rebuilding
it from `_core_runtime.provider`. ProviderManager refresh still reaches
`set_query_service` through the deferred sink and updates both recall and semantic
extraction.

Dream execution asks the injected runner to run, while Session Memory retains
permission gating, status start/stop, reload/error reporting, invalidation, and
dynamic prompt refresh.

## Dream Domain and Adapter

`dream.py` retains only pure context collection/projection, read-root input
validation policy, plan parsing/validation, snapshot checking, atomic apply, and
coordination through narrow ports.

`DreamCoordinator` receives:

- `SessionRepository`
- `ProjectIdentity`
- a `SessionMemoryView` exposing only `load()`
- `DreamAgentFactory`
- `ChildUsageRecorder`

`DreamAgentRunner.run_once` returns a typed result with text/input/output token
fields, and `close` is always awaited in `finally`.

The Agent composition layer owns the concrete restricted child subclass and
factory. The factory explicitly:

- selects only the three named tools and requires `read_only` capabilities;
- supplies a non-owning child ToolEnvironment view;
- passes `mcp_enabled=False` and `is_sub_agent=True`;
- excludes the nested agent, shell, and write tools by construction;
- fixes `permission_mode="bypassPermissions"` only inside the already restricted
  registry;
- fixes `max_turns=DREAM_MAX_TURNS`;
- disables project PreToolUse hooks;
- validates and resolves every read path against project/Memory roots before
  dispatch.

The domain continues to frame all source material as untrusted JSON, validate the
whole declarative plan before writes, reject snapshot changes, stage writes,
replace atomically, and restore every affected file plus the Memory index on
failure.

## Subagent Factory

Delete `SubagentFactoryHost`. Add a typed `ChildAgentConfig` projection and a
provider callable that returns it. The factory stores exactly registry,
environment, child-config provider, and permission view. It derives child
permission from the live view and passes explicit Agent constructor keywords.

This remains a concrete child constructor. It does not expose arbitrary services
or grow into a generic dependency container.

## Architecture Enforcement

Extend the existing AST architecture suite to enforce:

- no Agent/Core Runtime symbols or private runtime access in Autonomy/Learning;
- no Agent symbol or forbidden tool/provider/core fields in Session Memory;
- no Agent import, constructor argument, or field access in Dream;
- no `agent`/`host` parameters on the scoped domain constructors;
- no new RuntimeContext/AgentServices/DomainContext or equivalent scoped
  `*Services` class;
- no forbidden `Any` annotations on the migrated protocols;
- concrete Dream adapter placement and explicit security constructor flags.

Behavior tests remain the authority for control flow and safety. Architecture
tests prevent the wide dependency from silently returning.

## Compatibility, Rollback, and Risk

There is no compatibility layer. Tests and composition sites move directly to the
new constructors, and obsolete hosts/private seams are deleted.

Primary risks are constructor-order cycles, stale Provider queries after a model
change, Dream security drift while moving the child adapter, and accidental
overwrite of the pre-existing Dream test edit. Each risk has a focused test and a
rollback point in the implementation plan. The whole change is one responsibility
migration and is expected to remain within the repository PR size limit.
