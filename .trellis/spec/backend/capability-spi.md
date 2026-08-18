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

class TurnParticipant(Protocol):
    async def before_turn(self, user_message: str) -> None: ...
    async def after_turn(self) -> None: ...

class SessionParticipant(Protocol):
    async def on_new_session(self) -> None: ...
    async def on_restore_session(self) -> None: ...

@dataclass(frozen=True, slots=True)
class CapabilitySpec:
    name: str
    tool_sources: tuple[ToolSource, ...] = ()
    prompt_layers: tuple[PromptLayer, ...] = ()
    turn_participants: tuple[TurnParticipant, ...] = ()
    session_participants: tuple[SessionParticipant, ...] = ()
    resources: tuple[AsyncCloseable, ...] = ()
    requires: frozenset[str] = frozenset()
```

`CapabilityRegistry` resolves explicit dependencies, aggregates the slots above
in dependency order, and closes resources in reverse dependency order. It is an
aggregation mechanism, not a service locator, dependency-injection container,
provider owner, or mutable runtime-state store.

`CapabilityRuntime` dispatches turn/session lifecycle methods and close. Generic
context preparation and compaction remain owned by `ContextManager` and
`ContextCompactor`; the Capability SPI has no per-request projection slot.

## Invariants

1. `lion_code.capabilities` does not import `Agent`, `AgentRuntimeCoordinator`,
   or `AgentHarness`.
2. `CapabilitySpec` is frozen and normalizes all sequence contributions to
   tuples and dependencies to a frozenset.
3. Missing and circular dependencies fail during resolution.
4. Capability tools capture narrow commands at construction and never recover
   a service locator from `ToolContext`.
5. Capabilities consume read-only Kernel views and ports instead of mirroring
   permission, session, usage, cancellation, Plan, or provider state.
6. The built-in graph contains Plan, SubAgent, and Skill capabilities where the
   selected Profile requires them. No Memory, Dream, or Learning capability is
   registered or replaced by a placeholder.
7. The zero-extension registry is valid. FullProfile must also remain runnable
   when any one of Plan, Skill, SubAgent, or a third-party `CapabilitySpec` is
   omitted; Kernel and Harness do not branch on a capability name.

## Retained built-ins

- `PlanCapability` contributes Plan tools, a live prompt layer, and session
  lifecycle participation.
- `SubagentCapability` contributes the `agent` tool and delegates child usage,
  status, errors, and closure to `SubagentExecutor`.
- `SkillCapability` contributes the Skill tool and uses the same child executor.

Future capabilities may add the existing generic slots or closeable resources,
but must not add a second history store, writer, or context projection path.
The legacy-removal guard rejects only the deleted architecture and explicitly
does not reserve the generic name `MemoryCapability`; a new Memory system is a
separate design task and is not specified here.
