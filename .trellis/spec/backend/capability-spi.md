# Capability SPI

This contract defines the extension mechanism for Agent-level capabilities.
It is executable architecture, not a migration plan.

## 1. Scope and Trigger

Apply this guide whenever adding a new Agent-level capability (Browser,
Sandbox, Checkpoint, Scheduler, ComputerUse, etc.) or modifying the
``lion_code.capabilities`` package.

The separation is strict:

- Kernel and Capability are distinct layers.
- A Capability declares *what the Agent can do*, not *how the Agent runs*.
- Core, Provider, ToolRuntime, Session, Permission, Usage, ExecutionControl,
  Context, and Agent are Kernel—they must not be Capability-ized.
- ``CapabilityRegistry`` is an extension contribution organizer, NOT a service
  locator or dependency-injection container.

## 2. Public Signatures

~~~python
class AsyncCloseable(Protocol):
    async def close(self) -> None: ...

class ToolSource(Protocol):
    def tools(self) -> Sequence[LionTool]: ...

class PromptLayer(Protocol):
    @property
    def layer_id(self) -> str: ...
    def render(self) -> str: ...

class TurnParticipant(Protocol):
    async def before_turn(self) -> None: ...
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

class CapabilityRegistry:
    def register(self, spec: CapabilitySpec) -> None: ...
    def resolve(self) -> tuple[str, ...]: ...
    @property
    def tool_sources(self) -> tuple[ToolSource, ...]: ...
    @property
    def prompt_layers(self) -> tuple[PromptLayer, ...]: ...
    @property
    def turn_participants(self) -> tuple[TurnParticipant, ...]: ...
    @property
    def session_participants(self) -> tuple[SessionParticipant, ...]: ...
    @property
    def resources(self) -> tuple[AsyncCloseable, ...]: ...
    async def close_all(self) -> None: ...
~~~

## 3. Contracts

### Kernel–Capability Separation

1. ``lion_code.capabilities`` must not import ``lion_code.agent``,
   ``lion_code.agent_lifecycle``, or ``lion_code.agent_runtime``.
2. ``lion_code.capabilities`` must not reference ``AgentHarness`` in any form.
3. ``CapabilityRegistry`` must not import ``Agent``, create ``Provider``
   objects, create ``Session`` objects, modify ``Permission``, or hold
   runtime state beyond the registry itself.
4. No ``CapabilityContext``, ``ServiceLocator``, or monolithic
   ``AgentCapability`` interface with a dozen lifecycle hooks.

### CapabilitySpec Immutability

1. ``CapabilitySpec`` is a frozen, slotted dataclass—its fields cannot be
   mutated after construction.
2. ``requires`` is a ``frozenset[str]`` of capability names that must be
   initialized before this one.  Dependency ordering is explicit; no priority
   numbers or implicit ordering.

Construction must normalize every sequence contribution to a tuple and
``requires`` to a frozenset before the spec is exposed. ``frozen=True`` only
protects the dataclass attributes; retaining a caller-owned list or set would
still allow mutation behind the registry's dependency-order cache.

### Dependency Resolution

1. Missing dependencies raise ``MissingDependencyError`` at resolve time,
   naming both the requiring and missing capabilities.
2. Circular dependencies raise ``CircularDependencyError`` at resolve time,
   naming all unresolved capabilities.
3. Capabilities with no inter-dependencies preserve their registration order
   (stable topological sort).
4. The cached order is invalidated on each new ``register()`` call and
   lazily recomputed on the next property access or ``resolve()`` call.

### Aggregated Extension Slots

1. Each aggregated property (``tool_sources``, ``prompt_layers``,
   ``turn_participants``, ``session_participants``, ``resources``) returns
   contributions in dependency-resolved order, flattening all capabilities.
2. Properties auto-resolve lazily—callers do not need to call ``resolve()``
   explicitly unless they want to fail fast.

### Resource Closure

1. ``close_all()`` closes resources in reverse dependency order (most
   dependent first).
2. Within a single capability, resources are closed in reverse declaration
   order.
3. All resources are attempted even if one raises; the first exception is
   re-raised after all closures complete.

### State Ownership Preservation

1. The Capability SPI must not reintroduce mirrored mutable state
   (``permission_mode``, ``session_id``, ``plan state``, ``usage counters``,
   ``cancelled``).
2. Future capabilities that need access to Kernel state must consume the
   corresponding read-only View / Port (``PermissionView``, ``SessionView``,
   ``CancellationView``, ``PlanView``, etc.), not a god-object context.
3. This PR establishes the type contract only; defining Capability Ports for
   all Kernel state is deferred to future work.

## 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Register a capability with a duplicate name | ``DuplicateCapabilityError`` |
| Register a capability with an empty name | ``ValueError`` |
| Resolve with a ``requires`` referencing an unregistered name | ``MissingDependencyError`` naming both capabilities |
| Resolve with a circular dependency | ``CircularDependencyError`` naming all unresolved capabilities |
| Resolve with a self-referencing dependency | ``CircularDependencyError`` |
| No dependencies | Registration order preserved |
| Independent dependency groups | Each group respects internal ordering; inter-group order is registration order |
| ``close_all()`` with one failing resource | All resources attempted; first exception re-raised |
| ``close_all()`` with no resources | Completes without error |
| Property access before ``resolve()`` | Lazy resolution; no explicit call needed |
| New ``register()`` after ``resolve()`` | Cached order invalidated; next access re-resolves |

## 5. Executable Enforcement

The boundary rules are enforced by both import contracts and AST
architecture tests:

~~~powershell
lint-imports --no-cache
python -m pytest -q tests/architecture/test_runtime_boundaries.py
~~~

import-linter contracts in ``pyproject.toml``:

- ``lion_code.capabilities`` cannot import ``lion_code.agent``,
  ``lion_code.agent_lifecycle``, or ``lion_code.agent_runtime``.
- Existing contracts (Core, Providers, Application, TUI) automatically
  forbid ``capabilities`` where applicable because whitelist-based
  boundaries derive their forbidden set from ``ALL_ROOTS``.

AST tests in ``tests/architecture/test_runtime_boundaries.py``:

- ``test_capabilities_do_not_import_agent_engine``: capabilities source
  files must not import from ``agent``, ``agent_lifecycle``, or
  ``agent_runtime``.
- ``test_capabilities_do_not_reference_agent_harness``: capabilities
  source files must not reference ``AgentHarness`` in any form.
- ``test_capabilities_do_not_define_service_locator_or_god_context``:
  capabilities source files must not define ``CapabilityContext``,
  ``ServiceLocator``, or ``AgentCapability``.
- ``test_import_linter_config_matches_boundaries``: the import-linter
  contract in ``pyproject.toml`` matches the ``Boundary`` definition in
  ``_boundaries.py``.
- ``test_all_roots_matches_filesystem``: ``ALL_ROOTS`` includes
  ``capabilities`` (auto-discovered from the filesystem).

## 6. Tests Required

- ``tests/capabilities/test_capability_registry.py``: registration,
  duplicate rejection, dependency resolution (missing, circular,
  self-referencing, chained, stable ordering), aggregation of each
  extension slot, construction-time container normalization, close semantics
  (reverse order, error continuation, first-error re-raise), and full
  integration lifecycle.
- ``tests/architecture/test_runtime_boundaries.py``: capability boundary
  import, AgentHarness reference, and god-context prevention tests.
