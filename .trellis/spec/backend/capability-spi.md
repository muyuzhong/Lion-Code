# Capability SPI

This contract describes the current Agent capability extension surface. It is
an executable architecture contract, not a migration plan.

## Public slots

```python
class AsyncCloseable(Protocol):
    async def close(self) -> None: ...

class ToolSource(Protocol):
    def tools(self) -> Sequence[LionTool]: ...

class PromptLayer(Protocol):
    @property
    def layer_id(self) -> str: ...
    def render(self) -> str: ...

class ContextLayer(Protocol):
    @property
    def layer_id(self) -> str: ...
    def render(self, view: ContextView) -> str: ...

class SessionParticipant(Protocol):
    async def on_new_session(self) -> None: ...
    async def on_restore_session(self) -> None: ...

@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    name: str
    tool_sources: tuple[ToolSource, ...] = ()
    prompt_layers: tuple[PromptLayer, ...] = ()
    session_participants: tuple[SessionParticipant, ...] = ()
    resources: tuple[AsyncCloseable, ...] = ()
    context_layer: ContextLayer | None = None
```

CapabilityRegistry aggregates the slots above in registration order, including
non-None context_layer values, and closes resources in reverse registration
order. It is an aggregation mechanism, not a service locator,
dependency-injection container, provider owner, or mutable runtime-state store.

CapabilityRuntime dispatches session lifecycle methods and close. Generic
context preparation and compaction remain owned by ContextManager and
ContextCompactor; ContextLayer only supplies a read-only per-request fragment
to that existing preparation path.

## Context projection contract

### 1. Scope / Trigger

The slot is used when a capability needs to expose current runtime facts in a
provider request without adding a canonical message, session entry, or
compaction input.

### 2. Signatures

ContextLayer.render(view: ContextView) -> str is called once per prepared
provider request. The layer_id is a stable string used for deterministic
render ordering.

### 3. Contracts

- PromptLayer describes relatively stable Agent identity and policy in the
  System Prompt.
- ContextLayer describes current runtime reality at the tail of prepared
  context.
- ContextView contains only immutable scalar/tuple projections of canonical
  messages and ContextRuntimeState.
- ContextManager drops blank fragments and combines non-blank fragments into
  one transient role=user <agent-state>...</agent-state> message.
- Rendered output is never passed to SessionRecorder, CompactionEntry, or
  ContextCompactor.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| context_layer is None | Registry returns no layer; old four-slot specs remain valid |
| Blank render output | No transient state message is appended |
| Multiple layers | Sort by layer_id before rendering and append exactly one message |
| Layer needs feature state | Read an existing owner through a narrow view; do not create a second owner |

### 5. Good / Base / Bad Cases

- Good: GitStatusLayer computes cwd/branch/dirty files during render.
- Base: a third-party CapabilitySpec supplies one stateless layer through
  Profile.extension_specs.
- Bad: store counters, failures, timestamps, or a second history inside a
  ContextLayer or ContextManager.

### 6. Tests Required

- Registry aggregation and nullable-slot compatibility.
- Frozen ContextView derivation from tool calls and failed tool results.
- Stable ordering, one-message tail placement, and exact no-layer projection.
- Absence from canonical history, JSONL, CompactionEntry, and compactor input.
- Reachable-object-graph ownership checks for a layer-bearing Profile.

### 7. Wrong vs Correct

Wrong:

    class ContextManager:
        self.todo_items = []

Correct:

    class TodoContextLayer:
        def render(self, view: ContextView) -> str:
            return render_current_todos(view)

The correct form keeps feature-specific state and projection in the capability
while the Kernel remains generic.

## Invariants

1. `lion_code.capabilities` does not import `Agent`, `AgentRuntime`,
   or `AgentHarness`.
2. `CapabilitySpec` is frozen and normalizes all sequence contributions to
   tuples.
3. Capability tools capture narrow commands at construction and never recover
   a service locator from `ToolContext`.
4. Capabilities consume read-only Kernel views and ports instead of mirroring
   permission, session, usage, cancellation, Plan, or provider state.
5. Context layers are projections only: they do not write canonical messages,
   JSONL, compaction entries, or mutable counters.
6. The built-in graph contains AgentState/GitStatus for Coding and Full
   profiles, Plan/SubAgent/Skill where the selected Profile requires them, and
   no Memory, Dream, or Learning capability.
7. The zero-extension registry is valid. FullProfile must also remain runnable
   when any one of Plan, Skill, SubAgent, or a third-party `CapabilitySpec` is
   omitted; Kernel and Harness do not branch on a capability name.

## Retained built-ins

- `PlanCapability` contributes Plan tools, a live prompt layer, and session
  lifecycle participation, plus a transient `Task` ContextLayer.
- `AgentStateLayer` contributes Time, Context utilization, Activity, and Recent
  failures for Coding/Full prepared requests.
- `GitStatusLayer` contributes uncached cwd, branch, and dirty-file status.
- `SubagentCapability` contributes the `agent` tool and delegates child usage,
  status, errors, and closure to `SubagentExecutor`.
- `SkillCapability` contributes the Skill tool and uses the same child executor.

Future capabilities may add the existing generic slots or closeable resources,
but must not add a second history store, writer, or context projection path.
The legacy-removal guard rejects only the deleted architecture and explicitly
does not reserve the generic name `MemoryCapability`; a new Memory system is a
separate design task and is not specified here.
