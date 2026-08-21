# Error Handling

> Lion represents expected runtime failures as typed Core/application events or
> structured tool results.  Catch at the boundary that can make an informed
> recovery decision; do not hide a programming or orchestration failure behind an
> unrelated UI message.

## Current error channels

| Boundary | Expected failure representation | Current example |
|---|---|---|
| Tool execution | `ToolResult(content=..., is_error=True)` | `lion_code/tooling/runtime.py::ToolRuntime.execute` returns this for unknown tools and caught tool/middleware exceptions. |
| Workspace snapshot / rollback | Snapshot creation blocks an unsnapshotted mutating/process call with a structured tool error; restore returns a pre-restore ID and rollback returns a structured result | `lion_code/tooling/middleware.py::WorkspaceSnapshotMiddleware` and `lion_code/tooling/runtime.py::ToolRuntime.rollback` keep recovery at the Tool Runtime boundary. |
| Permission / hook / freshness policy | Structured error `ToolResult`, not an exception to the model loop | `lion_code/tooling/middleware.py` returns denial, confirmation, hook and read-freshness results with `is_error=True`. |
| Provider/model run | Canonical `AssistantMessage(stop_reason="error", error_message=...)` and related Core events | `lion_code/core/messages.py` defines the canonical error fields; `TerminalRenderer` renders the resulting event. |
| Application stream | Forward the mapped event; unstructured run exceptions propagate after queue cleanup | `lion_code/application/session.py::LionCodingSession._drive`. |
| CLI / REPL process edge | Catch, present with `ui.print_error`, and exit or continue as that interface requires | `lion_code/__main__.py` catches command/action exceptions at the REPL and `main()` boundary. |

## Rules for new code

- Return a structured `ToolResult(is_error=True)` for an expected tool failure,
  permission refusal, cancellation, invalid hook outcome, or failed middleware
  operation.  The Core loop can then report the result back to the model and the
  frontend can render the same outcome.
- Use the canonical assistant error fields/events for provider outcomes.  Do not
  create a parallel provider-specific error history or print directly from a
  provider implementation.
- Catch narrow operational errors where behavior is deliberately different.  For
  example, `SessionRepository.list_sessions()` skips one unreadable or invalid
  session, while a direct session load is allowed to surface the error.
- A broad catch is justified only at an existing containment boundary: the tool
  runtime converts arbitrary tool failures to a structured result, and the CLI
  top level converts an uncaught process failure to terminal output.  Do not copy
  `except Exception` into ordinary business logic just to keep execution going.
- Preserve cancellation semantics.  `asyncio.CancelledError` is handled
  separately during overflow compaction; do not turn it into a successful retry.

## Context-overflow recovery (current application contract)

`LionCodingSession._drive()` recognizes only a canonical terminal assistant error
whose message identifies a context/input/token-length overflow.  It may run one
recovery attempt, in this order:

```text
SessionAgentEnd(will_retry=True)
-> CompactionStart(reason="overflow")
-> CompactionEnd(aborted=False, will_retry=True)
-> AutoRetryStart(attempt=1, max_attempts=1, delay_ms=0)
-> retry Core events
-> SessionAgentEnd(will_retry=False)
-> AutoRetryEnd
-> AgentSettled
```

- A quota or generic service error does not enter this recovery path.
- If compaction has no safe old context, raises, or is cancelled, emit a terminal
  `CompactionEndEvent(..., will_retry=False)` and do not retry.
- If the retry fails or aborts, emit one `AutoRetryEndEvent(success=False, ...)`;
  never loop automatically.
- If the underlying run itself raises unexpectedly, `_drive()` drains/cleans up
  its queue and propagates the exception.  It does not pretend the run settled.

## Supervisor control recovery

`lion_code.supervisor.Supervisor` makes long-running retry decisions only from
the public Agent result and its injected `RetryPolicy`:

- `stop_reason == "completed"` becomes terminal success.
- An allowlisted stop reason becomes `retry_wait` only while the attempt count
  is below `RetryPolicy.max_attempts`; the injected Scheduler owns the wait.
- `aborted`/`cancelled` and an explicit `Supervisor.cancel()` request become a
  terminal cancelled state and never enter retry policy.
- Factory, session-restore, public-result-contract and Agent-close failures are
  represented as control-plane stop reasons. They are retryable only when the
  caller explicitly includes that reason in the policy.
- A checkpoint records only the next execution decision and session reference.
  It does not replace canonical session history or snapshot an in-flight Agent.

### Supervisor public control contract (PR10)

#### 1. Scope / trigger

This contract applies when a caller creates a `Supervisor` for a goal that may
cross process or attempt boundaries. It does not change the one-shot Agent
execution contract or the application-owned overflow retry.

#### 2. Signatures

The injected factory must return a public structural port with these operations:

```text
session_id -> str
subscribe(listener) -> unsubscribe callback
run(prompt, timeout?) -> PublicAgentResult
restore(session_id) -> bool
cancel() -> None
close() -> Awaitable[None]
```

`Supervisor.cancel()` is the control-plane cancellation command. It is distinct
from cancellation of the caller's `Supervisor.run()` task.

#### 3. Contracts

- `restore(session_id)` is required; Supervisor does not probe private runtime
  attributes or fall back to an older alias such as `resume()`.
- An explicit `Supervisor.cancel()` always persists a terminal `cancelled`
  checkpoint and returns a `SupervisorResult` with that status, including while
  waiting in the injected Scheduler.
- A caller-driven `asyncio.CancelledError` remains a caller cancellation and is
  re-raised after the best-effort terminal checkpoint write.
- Retry decisions use only the public result stop reason and the injected
  `RetryPolicy`; Agent message/content state is not an error-policy input.

#### 4. Validation & error matrix

| Condition | Result | Retry eligibility |
|---|---|---|
| public `restore()` returns `False` or raises | `session_restore_error` | only if explicitly allowlisted |
| factory, public run, result contract, or close fails | named control stop reason | only if explicitly allowlisted |
| public result is `completed` | terminal `completed` | none |
| result is `aborted`/`cancelled`, or Supervisor.cancel() is called | terminal `cancelled` | never |
| caller cancels `Supervisor.run()` | checkpoint best effort, re-raise `CancelledError` | caller decides |

#### 5. Good / base / bad cases

- Good: a retry-wait checkpoint is loaded, `cancel()` is called, and the next
  persisted state is terminal `cancelled` without creating another Agent.
- Base: a completed public result clears retry metadata and persists the public
  session reference.
- Bad: looking for `resume()` when `restore()` is absent, or retrying a
  cancellation because its stop reason appears in a generic allowlist.

#### 6. Tests required

- `tests/test_supervisor.py` asserts public restore, running-checkpoint restore,
  cancellation during an Agent run, cancellation during retry wait, and no
  retry after cancellation.
- Architecture tests assert Supervisor imports only Core public events and that
  Profile/Agent source does not know the Supervisor plane.

#### 7. Wrong vs correct

Wrong:

```python
restore = getattr(agent, "restore", None) or getattr(agent, "resume")
```

Correct:

```python
restored = await agent.restore(session_id)
```

The explicit port keeps session recovery public and prevents a compatibility
alias from silently widening the Supervisor boundary.

## Presentation and persistence

- `lion_code/observers/terminal.py::TerminalRenderer.handle` renders assistant
  errors and `ToolExecutionEndEvent(is_error=True)` through `ui.print_error`.
  It renders; it does not decide policy or retry.
- `SessionRecorder.handle` persists completed `MessageEndEvent` messages only.
  Incremental render events are not durable history, so do not rely on them for
  post-failure recovery.

## Representative tests

- `tests/integration/test_core_tool_runtime.py` verifies a middleware denial
  returns a structured error through the Core tool loop.
- `tests/runtime/test_terminal_renderer.py` verifies tool and assistant errors
  are presented as terminal errors.
- `tests/application/test_coding_session_ports.py` covers application event order,
  overflow compaction, cancellation and the one-retry limit.

## Avoid

- Do not raise a normal policy refusal through the whole Agent stack when it can
  be a `ToolResult(is_error=True)`.
- Do not infer overflow from any generic word such as `limit`; quota and service
  failures must remain ordinary terminal provider errors.
- Do not emit `AgentSettled` before a deliberate retry reaches a terminal state,
  or after an unstructured run exception.
