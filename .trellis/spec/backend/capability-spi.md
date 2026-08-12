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

class ToolCommand(Protocol):
    async def __call__(
        self,
        arguments: Mapping[str, JSONValue],
    ) -> ToolResult: ...

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
5. Capability-specific tools receive their command dependency when the
   ``ToolSource`` is constructed. Their ``LionTool.execute_fn`` may ignore
   ``ToolContext``; it must not recover a controller or service locator from
   that context at execution time.

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
- ``tests/capabilities/test_capability_migration.py``: MCP/Skill/SubAgent
  capability installation, disabled-capability tool absence, MCP fail-soft
  semantics, SubAgent permission inheritance, Skill tool delegation,
  close-does-not-double-release, and architecture boundary compliance.
- ``tests/tooling/test_capability_runtimes.py``: Skill inline/unknown/fork
  routing plus Subagent success/error conversion, status ordering, usage
  aggregation, and child closure.
- ``tests/architecture/test_tool_routing.py``: ToolContext/controller removal,
  forbidden Agent route names, and capability/runtime reverse-import guards.

## 7. Capability Contributions and Tool Bindings

The tool-bearing capabilities use construction-time command binding:

### McpCapability (``capabilities/mcp.py``)

- Implements ``TurnParticipant``: discovers and registers MCP tools on the
  first ``before_turn()``.
- Does **not** implement ``AsyncCloseable``: MCP process lifecycle
  (``disconnect_all``) remains owned by ``ToolEnvironment``.
- Receives narrow dependencies: ``McpManager``, ``ToolRegistry``, notice
  emitter, and init-flag accessors (callables, not a god-context).
- The init flag (``agent._mcp_initialized``) is shared via callables so
  tests and lifecycle code that check it continue to work.

### SkillCapability (``capabilities/skill.py``)

- ``create_skill_capability(runtime: SkillRuntime)`` implements
  ``ToolSource`` and captures the supplied runtime in the ``skill`` tool.
- ``SkillRuntime`` owns lookup, inline activation, unknown-skill handling, and
  fork dispatch. It does not receive or import ``Agent``.
- A fork delegates child construction and lifecycle to ``SubagentExecutor``;
  inline activation does not create a child.
- No ``TurnParticipant`` or ``AsyncCloseable`` slots.

### SubagentCapability (``capabilities/subagent.py``)

- ``create_subagent_capability(executor: SubagentExecutor)`` implements
  ``ToolSource`` and captures the supplied executor in the ``agent`` tool.
- ``SubagentFactory`` remains responsible only for child selection and
  construction. ``SubagentExecutor`` owns start/end status, ``run_once``,
  child usage merge, error conversion, and final child closure.
- No ``TurnParticipant`` or ``AsyncCloseable`` slots.

### PlanCapability (``capabilities/plan.py``)

- ``create_plan_capability(runtime: PlanRuntime)`` contributes only ToolSource
  tools for entering and exiting Plan mode.
- The tools call the bound ``PlanRuntime`` directly and preserve the
  ``ToolResult.terminate`` value returned by Plan approval.
- This slice does not add PromptLayer or SessionParticipant contributions.

### Dynamic wakeup tool

- ``create_wakeup_tool(runtime.schedule_wakeup)`` captures the command while
  the dynamic loop temporarily registers the tool.
- ``AutonomyRuntime`` owns ``pending_wakeup`` and delay clamping; the tool
  does not route through ``Agent``.

### Agent Composition Changes

- ``Agent.__init__`` creates ``SkillRuntime``, ``SubagentExecutor``, and
  ``PlanRuntime`` before registering the corresponding capabilities.
- Capability-provided tools are registered into fresh root registries. When a
  child receives a filtered registry, the composition root replaces the
  inherited capability tool objects with tools bound to the child runtimes;
  MCP and ordinary built-in tools remain shared by registry view.
- ``Agent._ensure_mcp_tools()`` is replaced by
  ``Agent._before_turn_capabilities()``, which iterates all
  ``TurnParticipant`` hooks without knowing what MCP is.
- ``AgentRuntimeCoordinator.chat()`` calls
  ``identity._before_turn_capabilities()`` instead of
  ``identity._ensure_mcp_tools()``, then invokes
  ``identity._after_turn_capabilities()`` from a ``finally`` block covering
  early exits, cancellation, and Provider/tool failures.
- ``SessionLifecycle.close()`` invokes
  ``identity._close_capabilities()`` so resources declared by the registry
  participate in the Agent shutdown chain; MCP process ownership remains with
  ``ToolEnvironment``.
- ``tooling/internal.py``'s ``create_internal_tools()`` no longer includes
  ``create_skill_tool()`` or ``create_agent_tool()``; they are provided by
  capabilities. Plan tools are provided by ``PlanCapability`` and the wakeup
  tool is registered only by the dynamic loop.
