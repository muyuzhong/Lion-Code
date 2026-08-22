# Logging and Observability Guidelines

> The current product has no Python `logging` / `getLogger()` usage and no
> structured application log pipeline.  Observability is carried by typed runtime
> events, interface rendering, and append-only session entries.  Do not describe
> a conventional log-level policy that the repository does not implement.

## What exists today

- `lion_code/observers/terminal.py::TerminalRenderer` consumes Core events and
  calls `ui.print_*` for text, tool calls/results, errors and lifecycle dividers.
- `lion_code/adapters/coding_session_backend.py::CodingSessionBackendAdapter`
  emits instance-scoped notices for product configuration/runtime situations;
  structured frontends receive them through `LionCodingSession` callbacks
  instead of a process-global output sink.
- `lion_code/session_runtime/recorder.py::SessionRecorder` records completed
  canonical session entries in JSONL.  It deliberately skips incremental
  rendering events.
- Tests observe these channels by patching render functions or using fake
  providers, for example `tests/runtime/test_terminal_renderer.py` and
  `tests/integration/test_agent_core_runtime.py`.

## Use the existing channels

| Need | Current channel |
|---|---|
| Show a user-facing tool or provider failure in a direct terminal run | A typed Core event rendered by `TerminalRenderer` / `ui.print_error`. |
| Show non-streaming information or error in Textual | The instance-level `LionCodingSession` notice callback. |
| Preserve completed conversational state for resume/replay | `SessionRecorder` -> `JsonlSessionStorage`. |
| Assert diagnostics in tests | Subscribe/patch the event consumer or inject a fake provider; do not scrape stdout as a hidden protocol. |

## Boundaries and exclusions

- Do not introduce `logging.basicConfig`, module-global loggers, or an unowned
  debug file as an incidental feature change.  There is no committed formatter,
  handler, retention rule, or log-level contract to match.
- Do not use `print()` inside Core, provider, tool, or TUI logic as a substitute
  for an event.  Terminal presentation is owned by the observer/`ui` boundary;
  Textual owns its own rendering.
- Do not use JSONL sessions as a generic diagnostic log.  They are canonical
  session history and may contain user/model/tool content; only completed Core
  entries are recorded by the existing recorder.  The repository demonstrates no
  separate redaction or diagnostic-log policy, so a feature needing one requires
  an explicit design rather than an undocumented new sink.  PR-S1 is the explicit
  exception: `lion_code/tooling/audit.py::ExecutionAuditLog` writes the fixed
  append-only `ExecutionEvent` schema to an injectable non-session `.audit` file,
  with sensitive file-write values redacted before serialization.
- Do not reintroduce a process-global UI sink or stdout capture to feed Textual.
  `runtime-boundaries.md` and `tui-interaction.md` record the current
  instance-scoped frontend ownership contract.

## Representative examples

```python
# TerminalRenderer handles presentation after the runtime has produced an event.
if event.is_error:
    print_error(event.result.text)

# SessionRecorder records final messages, not streaming fragments.
if isinstance(event, MessageEndEvent):
    await self.record_message(event.message)
```

Those patterns come from `lion_code/observers/terminal.py` and
`lion_code/session_runtime/recorder.py`; keep policy and persistence separate
from presentation.
