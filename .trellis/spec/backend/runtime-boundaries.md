# Runtime, Provider, Session, Memory, and Frontend Boundaries

## 1. Scope / Trigger

Use this contract when changing Agent construction, Provider configuration, child
agents, project identity, memory boundaries, session persistence or migration, or a
frontend that consumes Agent output.
These layers share one canonical Core history; adding a second message store, writer,
or process-global output bridge is an architecture regression.

## 2. Signatures

```python
def Agent.configure_api(
    *,
    model: str | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
    anthropic_base_url: str | None = None,
    use_openai: bool | None = None,
) -> None: ...

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

### Runtime and Provider

- Every `Agent` owns one `LionAgentRuntime`; both OpenAI-compatible and Anthropic
  requests go through `ModelProvider` implementations in `lion_code/providers/`.
- `LionAgentRuntime.messages` is the only active conversation state. Goal, loop,
  plan, learning, Dream, side queries, and child agents must not create
  protocol-private histories or SDK clients.
- `Agent.configure_api()` is an idle-only transaction. Build the replacement Provider
  first, replace it without clearing canonical history, update stored credentials and
  model, refresh the compactor, query service, and model-limit cache, then schedule
  the old Provider for closing.
- Child and Dream agents inherit the parent's stored Provider configuration and
  `terminal_output` setting. They must not infer credentials from a transport client.
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
| Old Provider after a successful swap | Close only after replacement; never close an active stream |
| New top-level session | Create and append one JSONL chain |
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

## 5. Good / Base / Bad Cases

- Good: `/model` switches from Anthropic to OpenAI-compatible while idle; history,
  usage recorder, and session writer keep their identity while all Provider-derived
  services use the replacement.
- Base: changing only the model updates the live Core model and records one model
  change without rebuilding the Provider.
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

## 6. Tests Required

- `tests/integration/test_agent_core_runtime.py`: both Provider protocols, idle and
  active hot-switch behavior, derived-service refresh, child inheritance, JSONL
  restore, and immutable legacy migration.
- `tests/session_runtime/`: append/replay ordering, compaction projection, incomplete
  tails, invalid legacy data, and same-ID precedence.
- `tests/runtime/test_terminal_renderer.py` and
  `tests/application/test_coding_session.py`: observer identity, usage continuity,
  structured-frontend terminal suppression, and notice callbacks.
- `tests/tui/test_tui_app.py`: two streaming turns, tool-row identity, one notice per
  action, no normal-delta full redraw, and shared Session Memory command dispatch.
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

## 7. Wrong vs Correct

### Wrong

```python
self._openai_messages = []
self._anthropic_messages = []
ui.set_sink(tui_sink)
legacy_path.replace(jsonl_path)
```

### Correct

```python
history = agent.core_runtime.messages
session = LionCodingSession(agent, terminal_output=False)
session.set_notice_fn(app_notice)
storage = repository.storage_for(session_id)
# Legacy input is read-only; SessionRecorder appends canonical entries to storage.
```
