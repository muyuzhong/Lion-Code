# Error Handling

> Lion represents expected runtime failures as typed Core/application events or
> structured tool results.  Catch at the boundary that can make an informed
> recovery decision; do not hide a programming or orchestration failure behind an
> unrelated UI message.

## Current error channels

| Boundary | Expected failure representation | Current example |
|---|---|---|
| Tool execution | `ToolResult(content=..., is_error=True)` | `lion_code/tooling/runtime.py::ToolRuntime.execute` returns this for unknown tools and caught tool/middleware exceptions. |
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
