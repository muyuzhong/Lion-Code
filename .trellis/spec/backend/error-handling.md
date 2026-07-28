# Error Handling

> Executable error and recovery contracts used by Lion's backend runtime.

## Scenario: Core context overflow recovery

### 1. Scope / Trigger

This contract applies when the Core provider ends a run with a canonical
`AssistantMessage(stop_reason="error")` whose `error_message` identifies a
context/input/token-length overflow. Provider transport retries and the legacy
SDK loop are outside this contract.

### 2. Signatures

- `Agent.compact_core_context_for_overflow() -> Awaitable[bool]`
- `LionCodingSession._drive(run) -> AsyncIterator[LionSessionEvent]`
- `SessionAgentEndEvent.will_retry: bool`
- `CompactionEndEvent(aborted, will_retry, error_message)`
- `AutoRetryEndEvent(success, attempt, final_error)`

### 3. Contracts

The success path emits this order exactly:

```text
SessionAgentEnd(will_retry=True)
→ CompactionStart(reason="overflow")
→ CompactionEnd(aborted=False, will_retry=True)
→ AutoRetryStart(attempt=1, max_attempts=1, delay_ms=0)
→ retry Core events
→ SessionAgentEnd(will_retry=False)
→ AutoRetryEnd
→ AgentSettled
```

Recovery reuses the current `LionAgentRuntime.continue_()` and append-only
`SessionRecorder`. It preserves the latest successful user turn plus the failed
prompt, while the original overflow Assistant error remains in durable history.
At most one automatic retry is allowed.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Context/input/token-length marker | Start overflow recovery |
| Generic quota or service error | Do not compact or retry |
| No older context can be safely replaced | `CompactionEnd(aborted=True, will_retry=False)` |
| Compactor raises | Same terminal event with `error_message` |
| User cancels during compaction | Cancel summary task; do not retry |
| Retry returns `error` or `aborted` | `AutoRetryEnd(success=False)`; do not loop |
| Unstructured run exception | Preserve `_drive` behavior: propagate; do not emit Settled |

### 5. Good / Base / Bad Cases

- Good: old history is summarized, recent context survives, one continuation
  succeeds, and the session settles.
- Base: a normal provider error produces the ordinary Agent end and Settled only.
- Bad: broad matching such as `"exceeded the limit"` treats RPM quota failures as
  context overflow; repeated recovery loops can burn requests indefinitely.

### 6. Tests Required

`tests/application/test_coding_session.py` must assert:

- the exact application-event order and `will_retry` values;
- the retry provider context and durable `CompactionEntry`;
- no compaction without replaceable old context;
- compaction failure and cancellation terminal behavior;
- one retry only, including retry failure;
- generic service/quota errors do not enter overflow recovery.

### 7. Wrong vs Correct

Wrong: emit `AgentSettled` after the first Core `AgentEnd`, then start a separate
retry loop or infer overflow from any message containing `"limit"`.

Correct: keep `_drive` running, classify only canonical Assistant errors with
context/input/token-length markers, reuse the same Core runtime and recorder,
then emit one final `AgentSettled` after recovery reaches a terminal state.
