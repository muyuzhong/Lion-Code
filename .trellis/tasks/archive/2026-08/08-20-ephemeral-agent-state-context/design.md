# Technical Design: Ephemeral Agent State Context

## Boundaries

The feature has four cooperating boundaries:

```text
CapabilitySpec.context_layer
        ↓
CapabilityRegistry.context_layers
        ↓ callback (Composition-owned wiring)
ContextManager.prepare(messages, runtime_state)
        ↓
prepared-only UserMessage → Provider request
```

- `capabilities/types.py` owns the public `ContextLayer` SPI and the immutable
  `CapabilitySpec` slot.
- `capabilities/registry.py` exposes a tuple of registered context layers. It
  remains an aggregation mechanism and never renders or owns runtime state.
- `context/types.py` owns frozen projection values (`ContextView`, utilization,
  tool-trace entries). The view contains only primitives and tuples derived from
  the input messages and `ContextRuntimeState`.
- `context/manager.py` owns the generic prepared-context projection. It will
  use a private structural render protocol rather than importing
  `lion_code.capabilities`; this preserves the existing Kernel → Capability
  dependency direction. Composition supplies a callback returning the registry's
  layers.
- `composition/agent_builder.py` wires the callback and registers built-in
  context capabilities for Coding/Full selections. Runtime modules remain
  feature-neutral and unchanged unless verification proves the existing hook is
  insufficient.

## Contracts and data flow

### ContextLayer

```python
class ContextLayer(Protocol):
    @property
    def layer_id(self) -> str: ...

    def render(self, view: ContextView) -> str: ...
```

The protocol docstring distinguishes `PromptLayer` (relatively stable System
Prompt semantics) from `ContextLayer` (per-request current-state projection).
`CapabilitySpec.context_layer` is a nullable field appended after the existing
fields so current positional construction remains valid; the Registry flattens
non-None values into `context_layers`.

### ContextView

Use frozen/slots values:

```text
ContextView
├── current_time: str
├── context_utilization: ContextUtilization
│   ├── used_tokens
│   ├── limit_tokens
│   ├── percentage
│   └── compaction: "not required" | "required"
├── tool_trace: tuple[ToolTrace, ...]
└── recent_failures: tuple[str, ...]
```

`ToolTrace` stores a tool name plus a bounded, deterministic argument summary;
it does not expose the mutable arguments mapping. `ContextView.from_messages()`
walks `AssistantMessage.tool_calls` in message order, creates trace entries,
and takes the last three `ToolResultMessage(is_error=True)` summaries. Failure
summaries keep only the first non-empty line and optional structured exit code;
tracebacks are never copied.

`ContextManager.prepare()` computes the view from the pre-projection message
sequence and the already available `ContextRuntimeState`. It first performs the
existing deep-copy/budget/snipping/clearing/protected-window flow unchanged,
then renders layers against that view. A view is not stored by the Manager.

### Prepared-only message

After all existing projection actions are complete:

1. obtain layers from the injected callback;
2. stable-sort by `layer_id` and render each layer;
3. drop blank fragments;
4. if at least one fragment remains, append one `UserMessage` whose content is
   `<agent-state>\n...\n</agent-state>`;
5. calculate `estimated_tokens` over the final prepared tuple.

The caller's input list is never mutated. The Core loop receives this extra
message only as the return value of `prepare_context`; it is not emitted as a
Core message event, so it cannot reach Harness canonical history, the recorder,
JSONL, compaction entries, or the compactor's tuple input.

### Built-in layers

- `capabilities/agent_state/` provides `AgentStateLayer`, a stateless renderer
  for Time, Context, Activity, and Recent failures. Activity groups identical
  trace summaries in first-seen order and emits `×N` for repeats.
- `capabilities/git_status/` provides `GitStatusLayer`, also stateless. Every
  render reads `Path.cwd()`, `git branch --show-current`, and
  `git status --porcelain --untracked-files=all` using argument-list subprocess
  calls with no shell. It renders cwd, branch, and dirty file paths; it owns no
  cache or workspace snapshot.
- `capabilities/plan/capability.py` adds `PlanContextLayer` to the existing Plan
  `CapabilitySpec`. It reads the existing `PlanRuntime` view and emits the Task
  line only while Plan is active. AgentStateLayer has no Plan import or branch.

AgentState and GitStatus specs are registered by Composition for profiles with
Coding tools (`CodingProfile` and `FullProfile`). The ContextManager callback
captures the completed layer tuple so Runtime does not reverse-link the
CapabilityRegistry. Explicit `extension_specs`
continue to work for all Profiles, including Minimal; no layer is registered by
default for Minimal, preserving its exact old projection.

## Compatibility and persistence

- Existing four-slot CapabilitySpec callers remain valid because the new slot is
  optional and appended.
- Existing `ContextManager` callers remain valid because context-layer callback
  defaults to empty.
- `runtime/context.py`, `runtime/agent.py`, `runtime/conversation.py`,
  `runtime/session.py`, `runtime/provider.py`, and `meta_agent.py` are not part
  of the design change.
- No canonical message model or JSONL entry schema changes. The transient
  `UserMessage` is intentionally never appended to the Core message list.
- The optional caller-provided `SessionBindings.context_manager` remains caller
  owned; Composition only injects built-in layers when it creates the default
  ContextManager. A custom manager can opt into layers through its existing
  construction seam.

## Test design

- Registry tests cover nullable slot normalization and context-layer aggregation.
- Context tests cover immutable view derivation, argument summaries, failure
  truncation, stable layer sorting, wrapper/message role, final token estimate,
  and unchanged projection with no layers.
- Integration tests capture Provider request messages and assert the state
  message is present there but absent from `agent.messages`, recorder JSONL,
  CompactionEntry replacement input, and compactor input.
- Architecture tests use the existing `_reachable_paths` traversal with a
  Profile containing a ContextLayer and assert the four named Runtime/Capability
  roots do not reach a new mutable owner; they also retain Runtime import
  direction checks.
- Capability removal tests build a Profile without the new specs and verify the
  existing MetaAgent/AgentRuntime graph still runs.

## Rollback shape

The change is isolated to the generic SPI/Context projection, three capability
packages, Composition wiring, and focused tests/specs. Rollback can remove the
new ContextLayer field/property, callback, built-in packages, Plan context slot,
and tests as one commit without touching canonical history or Runtime owners.
