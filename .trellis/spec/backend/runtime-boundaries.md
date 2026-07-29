# Runtime, Provider, Session, and Frontend Boundaries

## 1. Scope / Trigger

Use this contract when changing Agent construction, Provider configuration, child
agents, session persistence or migration, or a frontend that consumes Agent output.
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

### Frontends

- Structured frontends construct `LionCodingSession(agent, terminal_output=False)`
  and consume Core/application events. Instance-level notice, confirmation, and Plan
  callbacks cover non-streaming interaction.
- Direct Agent/REPL use keeps terminal output enabled and renders through `ui.print_*`.
- Never add a process-global sink or redirect stdout to feed Textual. The notice
  callback is cleared before the TUI closes its session on unmount; confirmation and
  Plan callbacks are reclaimed with that session. Toggling terminal output must not
  rebuild or replace `UsageObserver` or `SessionRecorder`.

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
  action, and no normal-delta full redraw.
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
