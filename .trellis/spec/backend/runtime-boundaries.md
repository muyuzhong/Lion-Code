# Runtime, Provider, Permission, Session, Memory, and Frontend Boundaries

## 1. Scope / Trigger

Use this contract when changing Agent construction, Provider configuration, child
agents, permission ownership or policy consumption, project identity, memory
boundaries, session persistence or migration, or a frontend that consumes Agent
output.
These layers share one canonical Core history; adding a second message store, writer,
or process-global output bridge is an architecture regression.

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
    def refresh_prompt(self) -> None: ...

def Agent.configure_api(
    *,
    model: str | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
    anthropic_base_url: str | None = None,
    use_openai: bool | None = None,
) -> None: ...

class AgentLifecycle:
    def configure_api(
        self,
        *,
        model: str | None = None,
        api_key: str | None = None,
        api_base: str | None = None,
        anthropic_base_url: str | None = None,
        use_openai: bool | None = None,
    ) -> None: ...
    def set_thinking_level(self, level: ThinkingLevel | str) -> ThinkingLevel: ...
    def apply_core_thinking_level(self, level: ThinkingLevel) -> None: ...

def Agent.set_terminal_output(enabled: bool) -> None: ...

class LionCodingSession:
    def __init__(self, agent: Agent, *, terminal_output: bool = False) -> None: ...
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
supplied.

For permission state, `PermissionController` owns one `PermissionState` containing
the active `PermissionMode` and `confirmed_values`. `Agent.permission_mode` is a
read-only facade, `ToolContext.permission` is the same live `PermissionView`, and
`PermissionMiddleware` receives only a `PermissionConfirmationSink` for cache writes.
`PlanRuntime` is the only business caller of `PermissionController.set_mode()`;
other layers invoke complete Plan commands.

The Agent composition root gives one `PlanState` to its only writer, `PlanRuntime`.
`ToolContext.plan` is the same live read-only View; Agent and lifecycle APIs are
delegates. Pending reset is completed only after persistence, replay and Core reset.

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
  `Agent` remains the composition root for MCP discovery,
  tools, Memory/Plan/Autonomy/Learning and UI callbacks, and exposes compatibility
  delegates such as `_core_runtime`, `_ensure_core_session_ready`, `chat()` and
  `close()`. The coordinator must not import `Agent` or create a second history,
  Provider, or JSONL writer.
- `Agent.configure_api()` is an idle-only transaction. Build the replacement Provider
  first, replace it without clearing canonical history, update stored credentials and
  model, refresh the compactor, query service, and model-limit cache, then schedule
  the old Provider for closing.
- `AgentLifecycle` owns that configuration transaction and both Thinking-change
  paths through `AgentLifecycleHost`; `Agent` exposes coordinator-backed Core,
  compactor, recorder and background-operation compatibility views while retaining
  configuration fields and Memory composition. The lifecycle module must not import
  `Agent` or create another Provider, message history, or session writer.
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
  it. Base prompt changes always call `PlanRuntime.refresh_prompt()`.
- `Agent._create_provider(**kwargs)` is the required host factory boundary. It reads
  `lion_code.agent.create_provider` at call time, so existing patches of that name
  affect initial construction, Provider swaps, and Thinking rebuilds. Do not import
  the factory directly into `agent_lifecycle.py`.
- `Agent._create_terminal_renderer()` is the corresponding renderer factory boundary:
  it resolves `lion_code.agent.TerminalRenderer` at call time, so terminal renderer
  patches remain effective while the coordinator rebuilds observers.
- Child and Dream agents inherit the parent's stored Provider configuration and
  `terminal_output` setting. They must not infer credentials from a transport client.
- `SubagentFactory` owns child tool selection and construction through a narrow
  parent-host contract. It imports `Agent` only while constructing a child to avoid
  a module-level cycle; `Agent` retains child execution, status presentation, usage
  accounting, error text, and resource closure.
- `LearningRuntime` owns explicit `/learn` transcript projection, evaluator decision
  parsing, and Skill creation through a narrow host contract. It reads the existing
  canonical Core history and uses the existing side-query path; `Agent` retains the
  public delegation and composition boundary, and no second history or Provider is
  created.
- Base product dependencies and imports do not include the OpenAI or Anthropic Python
  SDKs. The online context benchmark may use the `benchmark` optional extra, but the
  import must remain lazy so product startup and offline benchmark validation work
  without it.

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
  Session Memory updates. `Agent` remains the host for Core/Provider/TUI capabilities
  and exposes compatibility delegates; the coordinator must use its narrow
  `SessionMemoryHost` boundary rather than a global service locator.
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

- Structured frontends construct `LionCodingSession(agent, terminal_output=False)`
  and consume Core/application events. Instance-level notice, confirmation, and Plan
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
| Initial `permission_mode="plan"` | Create one active Plan path/prompt; exit falls back to `default` |
| Approval returns `keep-planning` or raises | Preserve active status, path, permission and Plan prompt for retry |
| `execute` / `clear-and-execute` | Exit to `acceptEdits`; only clear-and-execute records pending and terminates |
| Approval callback absent | Restore the entering mode without claiming user approval |
| Plan file missing / unreadable | Use `(No plan file found)` when absent; propagate read errors without partial exit |
| Active Plan clear / restore | Clear generates a new-session path; restore retains the active path |
| Active Plan new-session path generation fails | Surface the error and preserve the current Plan path, permission, and prompt |
| Context reset step fails | Keep `pending_context_reset`; never acknowledge a half-applied switch |
| Child construction | Inherit `plan` and `auto`; map every other parent mode to `bypassPermissions` |
| Hook trust in `dontAsk` | Continue to deny trust without treating tool permission bypass as Hook trust |

## 5. Good / Base / Bad Cases

- Good: `/model` switches from Anthropic to OpenAI-compatible while idle; history,
  usage recorder, and session writer keep their identity while all Provider-derived
  services use the replacement.
- Base: changing only the model updates the live Core model and records one model
  change without rebuilding the Provider.
- Good: `AgentLifecycle` receives the current `Agent` as a narrow host, builds a
  replacement through `host._create_provider()`, and only writes host fields after
  that construction succeeds.
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
- Good: `PlanRuntime.enter()` updates its state, permission and prompt; the existing
  `ToolContext.plan` immediately observes the new `Path`.
- Good: clear-and-execute keeps pending until replay and Core reset succeed.
- Bad: copying the path, clearing pending early, or rebuilding Plan prompt in a
  lifecycle layer creates a second writer.

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
- capabilities cannot depend on the Agent engine (`agent`, `agent_lifecycle`,
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
- Capability SPI source importing `agent`, `agent_lifecycle`, or
  `agent_runtime`; referencing `AgentHarness`; or defining
  `CapabilityContext`, `ServiceLocator`, or `AgentCapability` god-object
  types. See [Capability SPI](./capability-spi.md).

When a legitimate architecture move requires a new exception, change the
runtime code, this contract, the AST allowlist, and the focused test in one
reviewed change. Do not disable a contract, add a broad indirect-import
exception, or silently broaden an allowlist to make a regression pass.

## 7. Tests Required

- `tests/integration/test_agent_core_runtime.py`: both Provider protocols, idle and
  active hot-switch behavior, derived-service refresh, child inheritance, JSONL
  restore, immutable legacy migration, and that `Agent` composes
  `AgentLifecycle` while preserving the `lion_code.agent.create_provider` patch
  anchor for all Provider creation paths.
- `tests/session_runtime/`: append/replay ordering, compaction projection, incomplete
  tails, invalid legacy data, and same-ID precedence.
- `tests/runtime/test_terminal_renderer.py` and
  `tests/application/test_coding_session.py`: observer identity, usage continuity,
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
  `tests/application/test_coding_session.py`, and `tests/test_cli.py`: deterministic
  tool evidence, task/handoff persistence, filtered Dream candidates, and matching
  REPL/TUI command intents.
- `tests/test_context_formal_benchmark.py`: offline benchmark imports without the
  optional SDK and every dataset source snapshot exists.
- Before completion run the full test suite, `compileall`, changed-scope lint/type
  checks, dependency/import residual scans, and `git diff --check`.

## 8. Wrong vs Correct

### Wrong

```python
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
# agent_lifecycle.py: from .providers.factory import create_provider
```

### Correct

```python
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
session = LionCodingSession(agent, terminal_output=False)
session.set_notice_fn(app_notice)
storage = repository.storage_for(session_id)
# AgentLifecycle calls host._create_provider(**provider_kwargs).
# Legacy input is read-only; SessionRecorder appends canonical entries to storage.
```
