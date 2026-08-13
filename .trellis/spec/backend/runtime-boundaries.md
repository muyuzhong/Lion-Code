# Runtime, Provider, Permission, Session, Memory, and Frontend Boundaries

## 1. Scope / Trigger

Use this contract when changing Agent construction, Provider configuration, child
agents, permission ownership or policy consumption, project identity, memory
boundaries, session persistence or migration, or a frontend that consumes Agent
output.
These layers share one canonical Core history; adding a second message store, writer,
or process-global output bridge is an architecture regression.

## 1.1 Agent composition root

`AgentConfig` is a frozen value object containing only user/runtime settings;
`AgentDependencies` separately contains repositories, structural seams, supplied
tool registries/environments, and test factories. Neither type owns mutable
runtime state. `composition/agent_builder.py::build_agent_composition()` is the
one-shot Composition Root: it constructs state owners, Provider and permission
ports, tools, domain runtimes, capabilities, Core runtime, and the coordinator,
then returns an explicit `AgentComposition` value.

`Agent` does not retain the builder or a service registry. It remains the public
facade and implements application ports through delegates and a small amount of
use-case orchestration. New built-in capability wiring belongs in the composition
root; an injected capability can use `AgentDependencies.extra_capabilities`.

## 2. Signatures

```python
class CancellationView(Protocol):
    @property
    def cancelled(self) -> bool: ...
    def is_cancelled(self) -> bool: ...

class CancellationToken:
    @property
    def cancelled(self) -> bool: ...
    def is_cancelled(self) -> bool: ...
    def cancel(self) -> None: ...
    def reset(self) -> None: ...

class ExecutionControl:
    @property
    def cancelled(self) -> bool: ...
    @property
    def cancellation(self) -> CancellationView: ...
    def begin(self) -> None: ...
    def cancel(self) -> None: ...

class SessionView(Protocol):
    @property
    def id(self) -> str: ...
    @property
    def started_at(self) -> str: ...

class SessionIdentityState:
    def reset(self, id: str, started_at: str) -> None: ...

PermissionMode = Literal[
    "default",
    "acceptEdits",
    "bypassPermissions",
    "dontAsk",
    "plan",
    "auto",
]

class PermissionView(Protocol):
    @property
    def mode(self) -> PermissionMode: ...
    def is_confirmed(self, value: str) -> bool: ...

class PermissionConfirmationSink(Protocol):
    def confirm(self, value: str) -> None: ...

class PermissionState:
    mode: PermissionMode
    confirmed_values: set[str]

class PermissionController:
    @property
    def mode(self) -> PermissionMode: ...
    def set_mode(self, mode: PermissionMode) -> None: ...
    def is_confirmed(self, value: str) -> bool: ...
    def confirm(self, value: str) -> None: ...

PlanStatus = Literal["inactive", "active"]
PlanApprovalFn = Callable[[str], Awaitable[dict[str, Any]]]

class PlanView(Protocol):
    @property
    def is_active(self) -> bool: ...
    @property
    def file_path(self) -> Path | None: ...

class PlanState:
    status: PlanStatus
    file_path: Path | None
    previous_permission_mode: PermissionMode | None
    pending_context_reset: str | None

class PlanToolOutcome:
    content: str
    terminate: bool = False

class PlanRuntime:
    @property
    def is_active(self) -> bool: ...
    @property
    def file_path(self) -> Path | None: ...
    @property
    def pending_context_reset(self) -> str | None: ...
    def initialize(self) -> None: ...
    def set_approval_fn(self, fn: PlanApprovalFn | None) -> None: ...
    def toggle(self) -> PermissionMode: ...
    def enter(self) -> PlanToolOutcome: ...
    async def exit(self) -> PlanToolOutcome: ...
    def reset_for_new_session(self) -> None: ...
    def reset_after_restore(self) -> None: ...
    def complete_context_reset(self) -> None: ...

class PromptComposer:
    def get_system(self) -> str: ...
    def set_dynamic_context(self, dynamic_context: str) -> None: ...

class CapabilityLifecycle(Protocol):
    async def before_turn(self) -> None: ...
    async def after_turn(self) -> None: ...
    async def on_new_session(self) -> None: ...
    async def on_restore_session(self) -> None: ...
    async def close(self) -> None: ...

class ToolCommand(Protocol):
    async def __call__(
        self,
        arguments: Mapping[str, JSONValue],
    ) -> ToolResult: ...

class SkillRuntime:
    def __init__(self, executor: SubagentExecutor) -> None: ...
    async def __call__(
        self,
        arguments: Mapping[str, JSONValue],
    ) -> ToolResult: ...

class SubagentExecutor:
    async def __call__(
        self,
        arguments: Mapping[str, JSONValue],
    ) -> ToolResult: ...
    async def execute_skill_fork(
        self,
        *,
        skill_name: str,
        prompt: str,
        allowed_tools: list[str] | None,
        args: str,
    ) -> ToolResult: ...

def Agent.configure_api(
    *,
    model: str | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
    anthropic_base_url: str | None = None,
    use_openai: bool | None = None,
) -> None: ...

@dataclass(slots=True)
class ProviderState:
    model: str
    provider_kind: Literal["anthropic", "openai-compatible"]
    api_key: str
    openai_base_url: str | None
    anthropic_base_url: str | None
    thinking_enabled: bool
    thinking_level: ThinkingLevel

@dataclass(frozen=True, slots=True)
class ProviderView:
    model: str
    provider_kind: Literal["anthropic", "openai-compatible"]
    thinking_enabled: bool
    thinking_level: ThinkingLevel

class ProviderManager:
    def configure(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        anthropic_base_url: str | None = None,
        use_openai: bool | None = None,
    ) -> None: ...
    def set_thinking(self, enabled: bool) -> str: ...
    def set_thinking_level(self, level: ThinkingLevel | str) -> ThinkingLevel: ...
    def cycle_thinking_level(self) -> ThinkingLevel: ...
    def restore_configuration(
        self,
        *,
        model: str | None = None,
        thinking_level: str | None = None,
    ) -> None: ...
    def build_provider(
        self,
        level: ThinkingLevel | str | None = None,
    ) -> ModelProvider: ...

def Agent.set_terminal_output(enabled: bool) -> None: ...

class LionCodingSession:
    def __init__(
        self,
        backend: CodingSessionBackend,
        *,
        terminal_output: bool = False,
    ) -> None: ...
    def set_notice_fn(
        self,
        fn: Callable[[str, Literal["info", "error"]], None] | None,
    ) -> None: ...

class SessionRepository:
    def storage_for(self, session_id: str) -> JsonlSessionStorage: ...
    async def load(self, session_id: str) -> SessionState | None: ...

class SessionRecorder:
    async def handle(self, event: AgentEvent) -> None: ...
    async def record_compaction(
        self,
        *,
        summary: str,
        replaces_entry_ids: list[str] | None = None,
    ) -> CompactionEntry: ...

class SessionMemoryRepository:
    def load(self) -> SessionMemory: ...
    def save(self, memory: SessionMemory) -> SessionMemory: ...

def resolve_project_identity(cwd: Path | None = None) -> ProjectIdentity: ...

class TranscriptView(Protocol):
    @property
    def messages(self) -> tuple[AgentMessage, ...]: ...

class NoticeSink(Protocol):
    def emit(
        self,
        message: str,
        *,
        role: Literal["info", "error"] = "info",
    ) -> None: ...

class ConversationRunner(Protocol):
    async def chat(self, prompt: str) -> None: ...

class ModelQuery(Protocol):
    async def complete_text(
        self,
        *,
        system: str,
        user: str,
        max_output_tokens: int = 512,
    ) -> str: ...
    async def complete_messages(
        self,
        *,
        system: str,
        messages: Sequence[AgentMessage],
        max_output_tokens: int = 512,
    ) -> str: ...

class DreamAgentRunner(Protocol):
    async def run_once(self, prompt: str) -> DreamAgentResult: ...
    async def close(self) -> None: ...

class DreamAgentFactory(Protocol):
    def create(self, context: DreamContext) -> DreamAgentRunner: ...

class AutonomyRuntime:
    def __init__(
        self,
        *,
        conversation: ConversationRunner,
        transcript: TranscriptView,
        query: ModelQuery,
        notices: NoticeSink,
        cancellation: CancellationView,
        tool_registry: ToolRegistry,
        confirm: ConfirmCallback | None,
        usage: UsageLedger,
        budget: BudgetPolicy,
    ) -> None: ...

class LearningRuntime:
    def __init__(
        self,
        transcript: TranscriptView,
        query: ModelQuery,
        cwd: Path,
    ) -> None: ...

class SessionMemoryCoordinator:
    def __init__(
        self,
        *,
        identity: ProjectIdentity,
        repository: SessionMemoryRepository | None,
        transcript: TranscriptView,
        cancellation: CancellationView,
        permission: PermissionView,
        load_project_context: Callable[
            [ProjectIdentity], tuple[ProjectContextFile, ...]
        ],
        notices: NoticeSink,
        query: TextQueryService | None,
        dream_runner: DreamRunner,
        is_sub_agent: bool,
        status_callback: StatusCallback,
        refresh_context: Callable[[], None],
    ) -> None: ...

class DreamCoordinator:
    def __init__(
        self,
        *,
        repository: SessionRepository,
        identity: ProjectIdentity,
        session_memory: SessionMemoryView,
        factory: DreamAgentFactory,
        usage: ChildUsageRecorder,
    ) -> None: ...

class SubagentFactory:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        environment: ToolEnvironment,
        child_config: Callable[[], ChildAgentConfig],
        permission: PermissionView,
    ) -> None: ...
```

## Application Port Boundary

### 1. Scope / Trigger

This contract applies when a structured frontend consumes a coding session or
when Agent/runtime composition changes the application-facing conversation,
session, or settings surface.  The application owns the port definitions in
`lion_code/application/ports.py`; runtime code implements them structurally and
must not import the application package.

### 2. Signatures

```python
@dataclass(frozen=True, slots=True)
class QueueSnapshot:
    steering: tuple[str, ...] = ()
    follow_up: tuple[str, ...] = ()


class ConversationPort(Protocol):
    @property
    def messages(self) -> tuple[AgentMessage, ...]: ...
    def subscribe(self, listener: EventListener) -> Callable[[], None]: ...
    async def prompt(self, content: str) -> None: ...
    async def continue_(self) -> None: ...
    def steer(self, content: str) -> QueueSnapshot: ...
    def follow_up(self, content: str) -> QueueSnapshot: ...
    def queue_snapshot(self) -> QueueSnapshot: ...
    def cancel(self) -> None: ...
    @property
    def cancelled(self) -> bool: ...
    async def compact_for_overflow(self) -> bool: ...


class SessionPort(Protocol):
    @property
    def session_id(self) -> str: ...
    async def list_sessions(self) -> list[dict[str, Any]]: ...
    async def resume(self, session_id: str) -> bool: ...
    async def restore_latest(self) -> bool: ...
    async def new_session(self) -> None: ...
    async def compact(self) -> None: ...
    async def aclose(self) -> None: ...


class SettingsPort(Protocol):
    @property
    def cwd(self) -> Path: ...
    @property
    def model(self) -> str: ...
    @property
    def provider_name(self) -> str: ...
    @property
    def permission_mode(self) -> PermissionMode: ...
    @property
    def api_configured(self) -> bool: ...
    def provider_config(self) -> dict[str, Any]: ...
    def configure_provider(self, **kwargs: Any) -> None: ...
    @property
    def thinking_level(self) -> str: ...
    @property
    def available_thinking_levels(self) -> tuple[str, ...]: ...
    def set_thinking_level(self, level: str) -> str: ...
    def cycle_thinking_level(self) -> str: ...


class CodingSessionBackend(
    ConversationPort,
    SessionPort,
    SettingsPort,
    UsagePort,
    ControlPort,
    SessionMemoryPort,
    Protocol,
): ...
```

### 3. Contracts

- `LionCodingSession` stores one `_backend` and only calls the composed
  application ports.  It must not store an Agent, Core Runtime, or Harness.
- `messages` remains the canonical Core transcript projection.  The port does
  not expose Harness queue containers or `AgentMessage` queue objects.
- `QueueSnapshot` is a protocol-neutral Core value object and contains text
  tuples only.  `Agent` and `LionAgentRuntime` translate their internal queue
  state into it at the facade boundary.
- The application owns event bridging, `AgentSettledEvent` timing, and the
  one-at-most-one context-overflow compaction/retry policy.  Runtime owns the
  primitive prompt, continuation, cancellation, and compaction operations.
- Session and settings changes are commands on their respective backend owner;
  application code does not rebind a cached runtime after provider changes.

### 4. Validation & Error Matrix

| Condition | Required behavior |
|---|---|
| Backend queue snapshot | Return immutable `tuple[str, ...]` fields |
| Prompt while idle | Subscribe, drain events, then emit one settled event |
| Prompt while running without behavior | Raise `RuntimeError` |
| Prompt while running with `steer`/`follow_up` | Queue through the port and emit one `QueueUpdateEvent` |
| Overflow terminal assistant error | Compact once, retry once through `continue_()`, never loop |
| Abort before retry continuation | Emit failed retry and skip `continue_()` |
| Backend run exception | Drain/unsubscribe and propagate; do not emit settled |
| Provider configuration while running | Raise `RuntimeError` before calling the backend |

### 5. Good / Base / Bad Cases

- Good: `LionCodingSession(FakeCodingSessionBackend())` exercises event,
  cancellation, session, and settings policy without constructing an Agent.
- Base: `LionCodingSession(agent)` remains a valid composition-root call because
  `Agent` structurally implements `CodingSessionBackend`.
- Good: runtime converts queued `UserMessage` objects to a `QueueSnapshot`.
- Bad: application reads `backend.harness.queued_messages` or caches
  `agent.core_runtime` to bypass the port.
- Bad: moving overflow retry into the runtime would make application settled
  semantics and retry policy implicit rather than testable.

### 6. Tests Required

- `tests/application/test_coding_session_ports.py`: prompt event bridge,
  steering/follow-up, queue snapshots, cancel, settled ordering, overflow
  compaction/retry, abort during retry, session operations, and settings.
- `tests/application/fakes.py`: deterministic backend with no Agent import.
- `tests/integration/test_application_coding_session.py`: real Agent facade,
  Core events, provider replacement, JSONL/session persistence, and overflow.
- `tests/architecture/test_application_ports.py`: application import and
  Harness-storage guards, TUI/runtime direction, runtime reverse-import guard,
  and Fake backend source isolation.

### 7. Wrong vs Correct

```python
# Wrong: application knows runtime ownership and Harness queue types.
self._runtime = agent.core_runtime
self._runtime.harness.queued_messages.steering

# Correct: application consumes semantic ports only.
self._backend = backend
self._backend.queue_snapshot().steering
await self._backend.compact_for_overflow()
```

## 3. Contracts

### State Ownership

1. Every mutable runtime state has exactly one named Owner; consumers receive a
   read-only View and must not retain a writable mirror.
2. State changes cross layer boundaries as commands on that Owner, never as direct
   field assignments from observers or frontends.
3. One Agent composition passes the same state object through Core, Provider,
   ToolRuntime, middleware, Memory, and application adapters; callbacks and copied
   primitive fields are not state synchronization mechanisms.
4. Reset is a lifecycle transition performed before the next operation starts; it
   must not be hidden in a downstream consumer that can erase an already-issued
   command.
5. A state move is complete only when old fields, protocols, constructors, and
   writers are removed and architecture tests enforce the new single-owner boundary.

For the active Session identity, `SessionIdentityState` owns `id` and `started_at`,
while `SessionLifecycle` is the only post-construction writer for new/restore
transitions. `Agent.session_id`, `Agent.session_start_time`, `ToolContext.session`,
Recorder construction, and application session metadata are read-only projections.
For cancellation, `ExecutionControl` owns the one Core `CancellationToken` and
`AgentRuntimeCoordinator` owns begin/cancel orchestration, including Memory prefetch,
Core stream, compaction, explicit abort, and timeout side effects. Standalone
`AgentHarness` owns its local token only when no external cancellation view is
supplied. When a coordinator-owned `LionAgentRuntime` receives that external
view, its `cancel()` command must route back to `ExecutionControl.cancel()`;
calling `AgentHarness.cancel()` alone is a no-op because the Harness does not own
the external token.

For permission state, `PermissionController` owns one `PermissionState` containing
the active `PermissionMode` and `confirmed_values`. `Agent.permission_mode` is a
read-only facade, `ToolContext.permission` is the same live `PermissionView`, and
`PermissionMiddleware` receives only a `PermissionConfirmationSink` for cache writes.
`PlanRuntime` is the only business caller of `PermissionController.set_mode()`;
other layers invoke complete Plan commands.

The Agent composition root gives one `PlanState` to its only writer, `PlanRuntime`.
`ToolContext.plan` is the same live read-only View; Agent and lifecycle APIs are
delegates. Pending reset is completed only after persistence, replay and Core reset.

### Tool command and capability boundary

`ToolContext` carries execution state and middleware views only. It has no
`controller` field and is never used as a business-service locator. A
capability-specific tool captures a narrow `ToolCommand` when its `ToolSource`
is constructed; the existing four-argument `LionTool.execute_fn` signature
remains unchanged, and such a tool may ignore the context argument.

The concrete routing and ownership contract is:

- `skill` -> `SkillRuntime`. Lookup, inline activation, unknown-skill handling,
  and fork selection live there. A fork reuses `SubagentExecutor`.
- `agent` -> `SubagentExecutor`. The executor asks `SubagentFactory` for a
  child, emits start/end status, calls `run_once`, merges child input/output
  usage without changing parent turns/responses, converts child failures to an
  error `ToolResult`, and closes the child in `finally`.
- `enter_plan_mode` / `exit_plan_mode` -> `PlanRuntime` through the
  `PlanCapability` ToolSource. The same capability contributes a live
  `PlanPromptLayer` over `PlanView` and a `PlanSessionParticipant`; the tool
  adapter copies `terminate` from `PlanToolOutcome` into `ToolResult`.
- Dynamic `schedule_wakeup` -> `AutonomyRuntime.schedule_wakeup`. The runtime
  owns delay clamping and `pending_wakeup`; registration remains temporary to
  the dynamic loop.

`SubagentFactory` remains child construction and tool selection only. It must
not absorb execution lifecycle, status, usage, error conversion, or closure.
Capabilities and `SkillRuntime`/`SubagentExecutor` must not import `Agent` or
`AgentHarness`. Do not replace these narrow commands with a generic controller,
service locator, or aggregate Agent-services interface.

Usage has its own executable contract in
[Usage Ownership](./usage-ownership.md); this runtime composes that single Owner.

### Runtime and Provider

- Every `Agent` composes one `AgentRuntimeCoordinator`, which owns exactly one
  `LionAgentRuntime`; both OpenAI-compatible and Anthropic requests go through
  `ModelProvider` implementations in `lion_code/providers/`.
- `LionAgentRuntime.messages` is the only active conversation state. Goal, loop,
  plan, learning, Dream, side queries, and child agents must not create
  protocol-private histories or SDK clients.
- `AgentRuntimeCoordinator` owns Core assembly, observer subscription order,
  `SessionRecorder`, context projection/compaction, background cleanup, output
  capture, the supplied `ExecutionControl`, shared `UsageLedger` / `BudgetPolicy`,
  and chat/run orchestration through three narrow host ports
  (`RuntimeIdentityHost`, `SessionStateHost`, `MemoryTurnHost`).
  Clear/restore/compact/close orchestration is delegated to
  `SessionLifecycle` (in `session_lifecycle.py`), which calls back into the
  coordinator for shared `reset_core_observers` / `reset_session_usage`.
  `Agent` is the public facade over the composition root and exposes compatibility
  delegates such as `_core_runtime`, `_ensure_core_session_ready`, `chat()` and
  `close()`. The coordinator must not import `Agent` or create a second history,
  Provider, or JSONL writer.
- `Agent.configure_api()` is an idle-only transaction. Build the replacement Provider
  first, replace it without clearing canonical history, update stored credentials and
  model, refresh the compactor, query service, and model-limit cache, then schedule
  the old Provider for closing.
- `ProviderManager` owns that configuration transaction and all Provider/Thinking commands.
  `ProviderView` is the only provider/model/thinking projection exposed to consumers;
  credentials and base URLs stay inside the manager.
- `ProviderManager` receives only `ProviderRuntimePort`, `ModelContextControl`,
  `MemoryQuerySink`, `ConfigurationRecorder`, the provider factory Callable and a
  background scheduler. It never imports or accepts `Agent`, Core history or a
  runtime host aggregate.
- Replacement commands build every Provider and derived service before mutating
  Runtime or State. They then replace Runtime, commit State, refresh Context and
  Memory services, record the change, and schedule old Provider closure. A
  model-only change uses Runtime `set_model()` without rebuilding the Provider.
- `Agent` exposes facade delegates and does not retain Provider credentials,
  backend kind, Thinking mode or Thinking level as mutable fields. Session restore
  calls `ProviderManager.restore_configuration()`.
- `Agent.is_aborted` is a read-only facade over the coordinator's
  `ExecutionControl`. A new chat calls `begin()` before setup; explicit abort and
  timeout call the same coordinator cancellation path, while timeout retains its
  distinct final stop reason.
- Core Provider and Tool contracts consume `CancellationView`; one concrete
  `CancellationToken` reaches the Provider stream and Tool adapter. `ToolContext`
  stores `session: SessionView` and `cancellation: CancellationView`, never
  `session_id`, `cancellation_fn`, or a synthesized callback mirror.
- Permission policy remains stateless. It receives `PermissionMode` plus the current
  `Path | None` Plan file and preserves explicit-deny and Plan hard-boundary
  precedence. Middleware reads `ToolContext.permission.mode`, `is_confirmed()`, and
  `ToolContext.plan.file_path` for every call;
  default-mode approvals are cached through the narrow confirmation sink, while Auto
  classifier confirmations are deliberately not cached.
- Enter/exit, approval, path and prompt form one Runtime transaction.
  `keep-planning`, read errors and callback errors do not transition state.
  `clear-and-execute` retains pending until compaction, replay and Core reset finish.
- `/clear` regenerates an active path after Session identity reset; restore retains
  it. `PromptComposer.get_system()` renders the live Plan projection on every
  request, while dynamic context replacement updates only the Composer-owned
  tail.
- `Agent._create_provider(**kwargs)` is the required host factory boundary. It reads
  `lion_code.agent.create_provider` at call time, so existing patches of that name
  affect initial construction, Provider swaps, and Thinking rebuilds. The
  `ProviderManager` receives this method as a Callable and does not import the
  factory module directly.
- `Agent._create_terminal_renderer()` is the corresponding renderer factory boundary:
  it resolves `lion_code.agent.TerminalRenderer` at call time, so terminal renderer
  patches remain effective while the coordinator rebuilds observers.
- Child and Dream agents inherit the parent's stored Provider configuration and
  `terminal_output` setting. They must not infer credentials from a transport client.
- `SubagentFactory` owns child tool selection and construction from the concrete
  registry/environment, typed child-config provider, and live permission View. It
  imports `Agent` only while constructing a child to avoid a module-level cycle.
  `SubagentExecutor` owns child execution, status
  presentation, usage accounting, expected error text, and resource closure;
  `Agent` supplies the composition-time factory, ledger, and status callback.
- `LearningRuntime` owns explicit `/learn` transcript projection, evaluator decision
  parsing, and Skill creation from `TranscriptView`, `ModelQuery`, and an immutable
  cwd. It reads the existing canonical Core history and uses the existing side-query
  path; `Agent` retains the
  public delegation and composition boundary, and no second history or Provider is
  created.
- Base product dependencies and imports do not include the OpenAI or Anthropic Python
  SDKs. The online context benchmark may use the `benchmark` optional extra, but the
  import must remain lazy so product startup and offline benchmark validation work
  without it.

### Domain Runtime narrow ports

- `lion_code/domain_ports.py` owns four structural contracts only:
  `TranscriptView`, `NoticeSink`, `ConversationRunner`, and `ModelQuery`. They do
  not expose Agent, Core Runtime implementations, Provider implementations,
  tools, UI objects, or an API-readiness flag.
- `ProviderModelQuery` resolves the active Provider and model through live
  callables for every request. It owns the API-readiness precondition and
  preserves typed Core message roles for evaluator requests.
- `AutonomyRuntime` receives conversation, transcript, query, notice,
  cancellation, concrete registry, confirmation, Ledger, and Policy separately.
  `LearningRuntime` receives transcript, query, and an immutable cwd only.
- `SessionMemoryCoordinator` receives project identity/repository, transcript,
  cancellation and permission Views, the typed project-context loader, notice,
  current Memory query service, Dream command, sub-agent flag, status callback,
  and refresh callback. It does not receive Agent, ToolContext, ToolEnvironment,
  ToolRegistry, Provider, or Core Runtime implementations.
- `DreamCoordinator` is pure domain coordination over repository, identity,
  Session Memory View, typed child factory/runner, and the child usage command.
  The concrete restricted child lives in `dream_adapter.py`, selects only the
  three read-only tools, disables MCP and project hooks, prevents nesting,
  enforces `DREAM_MAX_TURNS`, and validates all resolved read paths against the
  project and Memory roots.
- `SubagentFactory` receives the concrete registry/environment, a typed
  `ChildAgentConfig` provider, and `PermissionView`. It remains a constructor;
  child execution, status, usage, errors, and closing remain in
  `SubagentExecutor`.

### Project Identity and Memory

- `resolve_project_identity()` uses the current Git worktree root when available;
  otherwise it uses the normalized current working directory. The resulting key
  isolates Auto Memory and Session Memory per project or worktree, so a repository
  subdirectory cannot create a second project state.
- Project instructions are read-only human-authored files. Load `CLAUDE.md` then
  `AGENTS.md` at every directory from project root to current cwd; deeper files win
  and `AGENTS.md` wins within one directory. The project-memory, Session Memory, and
  Dream lifecycles never write either file.
- Auto Memory is the durable, selectively recalled layer and only supports `user`,
  `feedback`, `project`, and `reference`. A `project` item records a long-lived,
  verified decision and its reason, never current work, goals, deadlines, or next
  steps.
- `SessionMemoryRepository` stores the lightweight project work state separately
  from JSONL: active goal/task, completed and pending work, decisions, blockers,
  relevant files, verification, handoff, and next step. Corrupt state is surfaced
  and never replaced by an empty automatic write.
- All three memory layers are temporary Provider projection only, in this priority:
  project instructions, fixed Session Memory, then selectively recalled Auto Memory.
  Project and Session layers are required overlays; canonical Core messages and JSONL
  never contain their XML wrapper or injected text.
- `SessionMemoryCoordinator` owns project identity, Session Memory persistence,
  project/turn overlays, Auto Memory recall coordination, Dream, and post-turn
  Session Memory updates. `Agent` is the facade for the graph assembled by
  `composition/agent_builder.py` and exposes compatibility delegates; the coordinator receives its
  transcript, query, state views, and commands independently rather than through an
  Agent-shaped host or global service locator.
- A root chat compresses canonical context first, reloads and fixes the Session Memory
  snapshot, collects any completed Auto Memory recall, starts recall for the next
  turn, and then calls the Provider. Tool-loop Provider calls reuse exactly that
  snapshot. At turn end deterministic tool evidence is saved before the bounded
  semantic patch; a failed patch cannot erase file or verification facts.
- `/clear` starts a new JSONL conversation but retains the current project's Session
  Memory. Restoring JSONL reloads the current project state rather than treating an
  old transcript as the work-state authority.

### Session

- `SessionRecorder` is the only runtime writer. It appends completed Core messages,
  model/thinking changes, and compaction entries through `JsonlSessionStorage` to
  `~/.lion-code/sessions/<session-id>.jsonl`.
- `SessionRepository` lists and replays JSONL. A new session never writes a monolithic
  `.json` snapshot.
- `session_runtime/legacy.py` is a read/migrate boundary only. Restoring a legacy
  `<session-id>.json` writes the canonical messages to the same ID's JSONL and then
  continues on JSONL. The source filename, bytes, and modification time remain
  unchanged.
- When both formats use the same ID, JSONL is authoritative and the legacy row is not
  listed as a second session.
- Sub-agents do not create durable session rows; their captured text returns to the
  parent tool call.
- Completing a project task clears only the active task pointer and keeps its summary
  in Session Memory. `/handoff` persists a resumable state summary without changing
  the JSONL transcript.
- `/dream` receives only filtered Session Memory candidate evidence. It can propose
  durable user preferences, explicit feedback, verified decisions with reasons,
  reusable failure-and-fix lessons, and external references; it rejects progress,
  pending work, temporary test failures, file lists, verification logs, handoffs,
  and next steps. Dream still writes only validated Auto Memory files.

### Frontends

- Structured frontends construct `LionCodingSession(backend, terminal_output=False)`
  and consume Core/application events. The composition root may pass `Agent`
  because it structurally implements `CodingSessionBackend`; frontends do not
  import the runtime engine. Instance-level notice, confirmation, and Plan
  callbacks cover non-streaming interaction.
- Direct Agent/REPL use keeps terminal output enabled and renders through `ui.print_*`.
- Never add a process-global sink or redirect stdout to feed Textual. The notice
  callback is cleared before the TUI closes its session on unmount; confirmation and
  Plan callbacks are reclaimed with that session. Toggling terminal output must not
  rebuild or replace `UsageObserver` or `SessionRecorder`.
- `CommandRegistry` parses `/task`, `/session-memory`, `/handoff`, and `/dream` into
  synchronous intents. `LionCodingSession` performs the state operation; both the
  REPL and TUI dispatch those same intents and do not add command text to JSONL.

## 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Provider/model switch while idle | Preserve canonical messages and refresh all Provider-derived services |
| Provider/model switch while processing | Raise `RuntimeError`; leave the active Provider and configuration unchanged |
| Replacement Provider construction fails | Keep the current Provider and canonical history unchanged |
| Lifecycle factory uses a patched `lion_code.agent.create_provider` | Use the patched factory for construction, API swap, and Thinking rebuild |
| Old Provider after a successful swap | Close only after replacement; never close an active stream |
| New top-level session | Create and append one JSONL chain |
| `/clear` or restore changes the active Session identity | `SessionLifecycle` resets the one `SessionIdentityState`; every `SessionView` observes it without a copied-field sync |
| Existing valid JSONL | Replay it and continue appending to the same file |
| Legacy JSON without JSONL | Read, migrate to same-ID JSONL, and preserve source bytes/name/mtime |
| Invalid legacy JSON | Raise `LegacySessionError` for direct load; skip it while listing |
| Same ID in JSON and JSONL | Prefer one JSONL session entry |
| Structured frontend | No terminal renderer; events/notices remain visible exactly once |
| Direct Agent or REPL | Terminal renderer/stdout remains available |
| Terminal-output toggle during a run | Raise `RuntimeError` |
| Git project root or its subdirectory | Resolve to one project key and state file |
| Non-Git cwd | Use its normalized cwd as the project identity |
| Corrupt Session Memory | Report it; keep the source file and skip automatic writes |
| `/clear` or JSONL restore | Keep/reload current project Session Memory; do not merge it into transcript |
| Tool loop after Auto Memory recall settles | Reuse the turn-start overlay snapshot until the next user turn |
| `/dream` candidate input | Include only filtered durable evidence; never grant writes outside Auto Memory |
| Explicit abort before Provider or Tool work starts | The shared token remains cancelled and the operation terminates as `aborted` |
| Timeout during a run | Use the shared cancellation command but report `timeout`, not `aborted` |
| New chat after an aborted run | Reset cancellation at the operation boundary before setup and complete normally |
| Controller changes mode after ToolContext construction | The existing `PermissionView` observes the new mode without replacement or synchronization |
| Repeated default-mode confirmation reason | Ask once, then read the Controller-owned confirmation cache |
| Repeated Auto classifier `confirm` decision | Ask every time and do not populate the confirmation cache |
| Initial `permission_mode="plan"` | Create one active Plan path; the live prompt projection is visible on the next request; exit falls back to `default` |
| Approval returns `keep-planning` or raises | Preserve active status, path and permission; the live Plan projection remains available for retry |
| `execute` / `clear-and-execute` | Exit to `acceptEdits`; only clear-and-execute records pending and terminates |
| Approval callback absent | Restore the entering mode without claiming user approval |
| Plan file missing / unreadable | Use `(No plan file found)` when absent; propagate read errors without partial exit |
| Active Plan clear / restore | Clear generates a new-session path; restore retains the active path |
| Active Plan new-session path generation fails | Surface the error and preserve the current Plan path, permission, and prompt |
| Context reset step fails | Keep `pending_context_reset`; never acknowledge a half-applied switch |
| Child construction | Inherit `plan` and `auto`; map every other parent mode to `bypassPermissions` |
| Hook trust in `dontAsk` | Continue to deny trust without treating tool permission bypass as Hook trust |
| Capability tool construction | Capture the narrow `ToolCommand`; do not look up an Agent/controller from `ToolContext` |
| Inline Skill | Return the resolved activation prompt without constructing a child |
| Unknown Skill | Return `ToolResult("Unknown skill: ...")` without a child |
| Fork Skill | Reuse `SubagentExecutor`; preserve start/end status, usage merge, error conversion, and close |
| Child `run_once` success | Return child text, merge input/output usage, emit end status, then close |
| Child construction or execution error | Return an error `ToolResult`, emit end status, and close any created child |
| Domain side query before API configuration | Raise `ModelQueryUnavailableError`; Auto Mode may ask through its explicit confirmation callback without incrementing denial counters |
| Confirmation callback replaced after Agent construction | Refresh the existing `AutonomyRuntime`; the next Auto decision must call the replacement |
| Session Memory repository identity differs from the injected project identity | Raise `ValueError` during coordinator construction before any Memory mutation |
| Dream has no durable evidence | Return an empty `DreamResult` without constructing a child |
| Dream child creation succeeds, then execution or parsing fails | Always close the child; do not apply a partial plan |
| Dream read resolves outside project or Memory roots | Deny the tool input before the concrete child executes it |
| Dream child inherits separate project-hook collections | Clear both the Agent hook list and the existing `ToolContext.hooks` collection |
| Dream plan is invalid, conflicts, or the Memory snapshot changed | Reject it; atomic apply restores every touched file and index on failure |
| Plan exit approval with clear-and-execute | Copy `terminate=True` into `ToolResult` and retain pending reset until Core reset succeeds |
| Dynamic wakeup command | Clamp delay, update `AutonomyRuntime.pending_wakeup`, and expose the tool only in the dynamic loop scope |

## 5. Good / Base / Bad Cases

- Good: `/model` switches from Anthropic to OpenAI-compatible while idle; history,
  usage recorder, and session writer keep their identity while all Provider-derived
  services use the replacement.
- Base: changing only the model updates the live Core model and records one model
  change without rebuilding the Provider.
- Good: `ProviderManager` receives narrow runtime/context/memory/recorder ports,
  builds a replacement through its injected factory, and only commits State after
  Runtime replacement succeeds.
- Bad: importing `create_provider` inside the lifecycle module bypasses the
  established test and compatibility patch point.
- Bad: keeping `_openai_messages` and `_anthropic_messages` beside Core history makes
  resume, compaction, and child inheritance protocol-dependent.
- Good: restoring `abc.json` creates `abc.jsonl`, continues there, and leaves
  `abc.json` byte-for-byte untouched.
- Bad: deleting or renaming the source file during migration removes the user's only
  rollback path.
- Good: Textual receives deltas, tool events, and one queued notice while stdout stays
  quiet.
- Bad: a module-global sink lets one frontend steal another Agent instance's output.
- Good: a task handoff changes `session-memory.json` while the JSONL chain remains a
  record of only user, assistant, and tool messages.
- Bad: appending a Session Memory overlay into harness messages makes compaction and
  resume treat injected project state as user conversation.
- Good: `SessionLifecycle` calls `session_state.reset(...)` once and Agent,
  ToolContext, Recorder, and application views immediately observe the new identity.
- Base: `Agent.session_id` and `Agent.is_aborted` remain public read-only facade
  properties while their mutable state lives in the owning runtime objects.
- Good: one `CancellationToken` is passed through Harness, Provider, Tool adapter,
  ToolRuntime, and middleware; `ExecutionControl` owns begin/cancel commands.
- Bad: copying `session_id` into ToolContext or wrapping `_aborted` in a callback
  recreates mirrored state and makes lifecycle transitions require manual sync.
- Bad: resetting cancellation inside an async generator can erase a cancel command
  issued after generator construction but before its first iteration.
- Good: an existing `ToolContext` observes `controller.set_mode("plan")` through its
  live `PermissionView`, and middleware records a default approval through
  `PermissionConfirmationSink.confirm()`.
- Base: `Agent.permission_mode`, Application, TUI, Session Memory, and child-agent
  construction read the current typed facade without receiving `PermissionState`.
- Bad: assigning `Agent.permission_mode`, copying it into
  `ToolContext.permission_mode`, or mutating `confirmed_values` in middleware creates
  multiple writers and requires manual synchronization.
- Good: `PlanRuntime.enter()` updates its state and permission; the existing
  `ToolContext.plan` and `PlanPromptLayer` immediately observe the new `Path`.
- Good: clear-and-execute keeps pending until replay and Core reset succeed.
- Bad: copying the path, clearing pending early, or rebuilding Plan prompt in a
  lifecycle layer creates a second writer; prompt composition must read the live
  `PlanView` instead.
- Good: `Agent` composes `AutonomyRuntime` from separate conversation, transcript,
  query, notice, cancellation, registry, confirmation, usage, and budget objects.
- Base: `LearningRuntime` receives only the canonical transcript View, one
  Provider-neutral query, and an immutable cwd.
- Bad: passing `agent`, `host`, `_core_runtime`, or an aggregate Context/Services
  object into a Domain Runtime recreates a service locator.
- Good: `DreamCoordinator` receives a typed child factory while
  `RestrictedDreamAgentFactory` alone imports and configures the concrete Agent.
- Bad: moving read-root checks, read-only tool selection, hook disabling, MCP
  disabling, nesting prevention, or turn limits into the model prompt weakens the
  executable Dream boundary.

## 6. Executable Enforcement

The boundary rules above are enforced by both import contracts and AST
architecture tests. They are regression gates, not advisory documentation:

~~~powershell
lint-imports --no-cache
python -m pytest -q tests/architecture/test_runtime_boundaries.py
~~~

pyproject.toml contains these six import-linter contracts:

- core cannot depend on providers, tooling, permission/Plan/Usage state, observers,
  application, or tui, including indirect paths.
- providers cannot depend on any Lion runtime layer other than core, including
  `plan_runtime`; direct
  import validation also requires provider source to use only core or its own
  package.
- application cannot depend on tui.
- tui cannot directly import a runtime engine layer. It consumes
  application / core events; config, prompt, and version remain narrow
  presentation/configuration exceptions.
- capabilities cannot depend on the Agent engine (`agent`,
  `agent_runtime`). The Capability SPI is a separate layer from the Agent
  composition root; see [Capability SPI](./capability-spi.md).
- Product code cannot import tests or benchmarks.

tests/architecture/test_runtime_boundaries.py parses production source and
also rejects patterns an import graph cannot express:

- Provider classes storing message-history fields named messages or history.
- The old _openai_messages or _anthropic_messages paths outside
  session_runtime/legacy.py. That module is a read-only legacy JSON converter,
  not a live Provider history.
- A defined or invoked process-global set_sink.
- Any new SessionRecorder construction. The only allowed construction sites
  are AgentRuntimeCoordinator.reset_core_observers() for the active runtime
  writer and Agent._migrate_legacy_core_session() for one-time legacy
  conversion. The latter must not become a second active session path.
- JsonlSessionStorage or entry_to_json_line escaping core/ or
  session_runtime/.
- Memory runtime code calling Harness mutation APIs or owning an
  AgentHarness. Overlay code may read a canonical snapshot and return a
  temporary projection only.
- `Agent._aborted`, `ToolContext.session_id`, `ToolContext.cancellation_fn`, duplicate
  Provider/Tool cancellation token protocols, or Session identity reset calls outside
  `SessionLifecycle`.
- `Agent.permission_mode` or `_confirmed_paths` instance fields,
  `ToolContext.permission_mode` or `confirmed_paths`, Permission state construction
  outside the Agent composition root, direct state writes outside
  `permission_state.py`, or `set_mode()` business calls outside `plan_runtime.py`.
- Former Agent Plan fields/helpers; `ToolContext.plan_file_path`; PlanState
  construction or mutation outside its owner; or lifecycle code rebuilding Plan
  state, permission or prompt by hand.
- Usage single-writer, composition, projection, and reverse-import scanners follow
  [Usage Ownership](./usage-ownership.md).
- Capability SPI source importing `agent` or
  `agent_runtime`; referencing `AgentHarness`; or defining
  `CapabilityContext`, `ServiceLocator`, or `AgentCapability` god-object
  types. See [Capability SPI](./capability-spi.md).
- `tests/architecture/test_composition_root.py` enforces one-shot builder
  construction, absence of whole-Agent runtime constructors, and capability
  registration without edits to facade/runtime/application/TUI modules.

When a legitimate architecture move requires a new exception, change the
runtime code, this contract, the AST allowlist, and the focused test in one
reviewed change. Do not disable a contract, add a broad indirect-import
exception, or silently broaden an allowlist to make a regression pass.

## 7. Tests Required

- `tests/integration/test_agent_core_runtime.py`: both Provider protocols, idle and
  active hot-switch behavior, derived-service refresh, child inheritance, JSONL
  restore, immutable legacy migration, and that `Agent` composes
  `ProviderManager` while preserving the `lion_code.agent.create_provider` patch
  anchor for all Provider creation paths.
- `tests/session_runtime/`: append/replay ordering, compaction projection, incomplete
  tails, invalid legacy data, and same-ID precedence.
- `tests/runtime/test_terminal_renderer.py` and
  `tests/integration/test_application_coding_session.py`: observer identity, usage continuity,
  structured-frontend terminal suppression, and notice callbacks.
- `tests/runtime/test_agent_runtime.py`: `agent_runtime` imports without importing
  `lion_code.agent`, and a constructed `Agent` exposes the coordinator's one Core
  runtime rather than a duplicate history.
- `tests/core/test_cancellation.py`, `tests/test_agent_run.py`, and
  `tests/tooling/test_runtime.py`: cancellation before first iteration, shared
  Provider/Tool signal propagation, explicit-abort versus timeout outcomes, and
  reset before a later chat.
- `tests/integration/test_agent_core_runtime.py`: clear/restore updates the single
  Session identity, ToolContext observes the live view, and a cancelled run can be
  followed by a successful turn.
- `tests/tooling/test_permission_policy.py` and
  `tests/tooling/test_permission_middleware.py`: explicit deny and Plan hard
  boundaries, live mode reads, default confirmation caching, Auto non-caching, and
  narrow confirmation writes.
- `tests/test_plan_runtime.py`: initialization, permissions, approvals, file errors,
  clear/restore, prompt refresh, pending and View identity.
- `tests/tooling/test_agent_runtime.py` and
  `tests/integration/test_agent_core_runtime.py`: Agent facade delegation, existing
  live View, clear-and-execute continuation, and reset failure.
- `tests/tooling/test_skill_registry_view.py`, `tests/test_hooks.py`, and
  `tests/integration/test_agent_core_runtime.py`: read-only Agent facade, live child
  inheritance, `dontAsk` Hook trust, and Plan approval transitions without
  ToolContext permission synchronization.
- `tests/tooling/test_capability_runtimes.py` and
  `tests/tooling/test_internal_tools.py`: construction-time command binding,
  Skill inline/unknown/fork behavior, child status/usage/error/closure, and
  capability-specific tool adapters that ignore ToolContext.
- `tests/architecture/test_tool_routing.py`: no ToolContext controller field,
  no removed Agent route names in production, and no Agent reverse-import from
  capabilities or the independent child runtimes.
- `tests/architecture/test_runtime_boundaries.py`: the PermissionState/Controller
  composition count, removed mirrors, write-site confinement, middleware port shape,
  and Core/Provider import ownership.
- `tests/tui/test_tui_app.py`: two streaming turns, tool-row identity, one notice per
  action, no normal-delta full redraw, and shared Session Memory command dispatch.
- tests/architecture/test_runtime_boundaries.py: import ownership, Provider private
  history, legacy path confinement, global-sink absence, SessionRecorder ownership,
  JSONL writer confinement, and Memory Overlay non-mutation rules.
- `tests/test_project_identity.py`, `tests/test_prompt.py`, and
  `tests/memory_runtime/test_core_integration.py`: project/worktree identity,
  root-to-cwd instruction precedence, non-destructive three-layer projection,
  `/clear`/restore lifecycle, and fixed per-turn overlays.
- `tests/test_session_memory.py`, `tests/test_dream.py`,
  `tests/integration/test_application_coding_session.py`, and `tests/test_cli.py`: deterministic
  tool evidence, task/handoff persistence, filtered Dream candidates, and matching
  REPL/TUI command intents.
- `tests/test_autonomy_goal_loop.py`, `tests/test_autonomy_flow.py`,
  `tests/test_learning.py`, and `tests/test_model_query.py`: explicit narrow
  construction, Goal/loop/classifier behavior, live confirmation replacement,
  role-preserving side queries, and unavailable-query handling.
- `tests/test_session_memory_coordinator.py`, `tests/memory_runtime/`, and
  `tests/test_dream.py`: Memory read/update and semantic extraction, repository
  identity validation, restricted Dream child construction, root checks, hook/MCP/
  nesting/turn limits, validated plans, close-on-error, and atomic rollback.
- `tests/architecture/test_runtime_boundaries.py`: migrated Domain modules do not
  import or reference Agent/Core Runtime, Dream does not accept Agent, forbidden
  Memory dependencies remain absent, and no Context/Services locator or wide
  `agent`/`host` constructor parameter appears.
- `tests/test_context_formal_benchmark.py`: offline benchmark imports without the
  optional SDK and every dataset source snapshot exists.
- Before completion run the full test suite, `compileall`, changed-scope lint/type
  checks, dependency/import residual scans, and `git diff --check`.

## 8. Wrong vs Correct

### Wrong

```python
self._autonomy = AutonomyRuntime(self)
self._learning = LearningRuntime(self)
self._session_memory = SessionMemoryCoordinator(host=self)
self._dream = DreamCoordinator(agent=self)
self._subagents = SubagentFactory(host=self)
self._openai_messages = []
self._anthropic_messages = []
self.tool_context.session_id = self.session_id
self.tool_context.cancellation_fn = lambda: self._aborted
self.permission_mode = "plan"
self.tool_context.permission_mode = self.permission_mode
self._plan_file_path = self._generate_plan_file_path()
self.tool_context.plan_file_path = self._plan_file_path
self._pending_core_context_reset = None
self.tool_context.confirmed_paths.add(reason)
ui.set_sink(tui_sink)
legacy_path.replace(jsonl_path)
# ProviderManager receives Agent._create_provider as a Callable factory seam.
```

### Correct

```python
self._autonomy = AutonomyRuntime(
    conversation=self,
    transcript=self._core_runtime,
    query=model_query,
    notices=self,
    cancellation=self._runtime_coordinator.cancellation,
    tool_registry=self.tool_registry,
    confirm=self._confirm_fn,
    usage=self.usage,
    budget=self.budget_policy,
)
self._learning = LearningRuntime(self._core_runtime, model_query, self.cwd)
self._dream = DreamCoordinator(
    repository=self._session_repository,
    identity=self._project_identity,
    session_memory=session_memory_view,
    factory=restricted_dream_factory,
    usage=self.usage,
)
history = agent.core_runtime.messages
session_id = agent.tool_context.session.id
cancelled = agent.tool_context.cancellation.cancelled
permission_mode = agent.tool_context.permission.mode
confirmed = agent.tool_context.permission.is_confirmed(reason)
plan_path = agent.tool_context.plan.file_path
outcome = agent.plan.enter()
await agent.plan.exit()
agent.plan.reset_for_new_session()
agent.plan.complete_context_reset()
session = LionCodingSession(backend, terminal_output=False)
session.set_notice_fn(app_notice)
storage = repository.storage_for(session_id)
# ProviderManager calls its injected factory after replacement validation.
# Legacy input is read-only; SessionRecorder appends canonical entries to storage.
```
