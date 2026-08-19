# PR10 Supervisor Plane — Design

## 1. Boundary decision

PR10 introduces one explicit `lion_code.supervisor` production boundary. The
boundary owns execution control around a public Agent contract; it does not
become a second Agent runtime and it does not enter any Profile or Composition
Root graph.

The public shape is intentionally external to Agent construction:

```python
Supervisor(
    agent_factory=...,  # selects Minimal/Coding/Full outside Supervisor
    goal=...,
    retry_policy=...,
    checkpoint_store=...,
)
```

`agent_factory` is the only place that chooses and constructs a Profile-backed
Agent. `MinimalProfile`, `CodingProfile`, `FullProfile`, `Agent`, and the
Composition Root remain unaware of Supervisor. A factory may return `Agent`,
`MetaAgent`, or a test double as long as it implements the public port below.

## 2. Current evidence and adversarial re-home decision

The current branch already removed all production callers of
`AutonomyRuntime`. The remaining `autonomy.py` / `autonomy_runtime.py` code is
an old client-command implementation:

- `/goal` judges transcript text through a side-model query and mutates a
  session-local dictionary.
- `/loop` owns a process-local sleep loop and dynamically injects
  `schedule_wakeup` into a private `ToolRegistry`.
- Auto Mode classifies a pending private tool call using private transcript,
  registry and confirmation state.
- The runtime also owns Agent usage/budget and cancellation views.

Only the first two concepts have a Supervisor-shaped intent, but their old
implementation depends on private Agent/Harness state and preserves a removed
command surface. PR10 therefore re-homes the control-plane behavior through
new public contracts rather than preserving those methods. The old command
parser, side-query adapter, transcript classifier and temporary wakeup tool are
deleted as historical residue. No old Agent method, alias, fallback or command
is retained.

The existing foreground context-overflow recovery in
`LionCodingSession` remains an application event-bridge policy: it already
uses application ports, consumes public events and preserves the current UI
event contract. PR10 does not duplicate or route that UI-specific policy through
the new long-running Supervisor.

## 3. Public Agent boundary

`supervisor.py` defines structural protocols without importing `Agent`,
`AgentRuntimeCoordinator`, `LionAgentRuntime`, `ToolRegistry`, Provider, or
TUI implementations:

```text
AgentPort
  session_id -> str
  subscribe(listener: PublicAgentEventListener) -> unsubscribe callback
  run(prompt, timeout?) -> PublicAgentResult
  restore(session_id) -> bool
  cancel() -> None
  close() -> Awaitable[None]

AgentFactory = Callable[[], AgentPort]
```

`PublicAgentResult` is structural. Supervisor reads only `session_id`,
`stop_reason`, and optional `error`; it never reads final text, messages,
Provider, UsageLedger, ToolRegistry or private runtime attributes.

The event listener consumes `core.events.AgentEvent` values. It maps public
event kinds to the durable execution phase (`running`, `recovery`, `waiting`,
or `cancelled`) but does not inspect implementation objects.

## 4. Goal, retry and scheduler contracts

### Goal

`Goal` is an immutable execution request containing a stable `id` and the
prompt to run. A plain string is accepted as a convenience and receives a
deterministic id. Goal completion is deliberately control-plane simple:
`PublicAgentResult.stop_reason == "completed"` is terminal success. Semantic
transcript judging and side-model goal evaluation are deferred to a future
independent policy; they are not recreated inside Supervisor.

### RetryPolicy

`RetryPolicy` is an immutable value with:

- positive `max_attempts`;
- initial delay, multiplier and maximum delay;
- an explicit allowlist of retryable public stop reasons.

It returns a bounded delay and permits a retry only when the current attempt is
below the limit and the public result is retryable. User cancellation never
enters this policy.

### Scheduler

`Scheduler` is a one-method async wait port. The default implementation uses
`asyncio.sleep`; tests inject a recording scheduler. It is used for retry
backoff and for a restored checkpoint whose `next_run_at` is still in the
future. PR10 does not install an OS/cloud scheduler: durable state makes a
future process able to resume, while the caller owns process/service lifetime.

## 5. Durable checkpoint contract

`SupervisorState` is the complete persisted shape. It contains only:

```text
goal_id / goal
phase / status
attempt
session_id
retry metadata (last public stop reason, retry count, next delay)
created_at / updated_at / next_run_at
```

It does not contain final text, messages, transcript fragments, tool calls,
Provider data, usage totals, user preferences, semantic content, embeddings,
or learned information. The checkpoint is an execution recipe and session
reference, not Agent history.

`CheckpointStore` has only `load(goal_id)` and `save(state)`. The in-memory
implementation is for tests; the JSON implementation writes one strict state
document atomically under a caller-owned directory. It is not backed by or
coupled to `SessionRepository`, `SessionRecorder`, or canonical session JSONL.
Extra fields are rejected on load so the durable boundary cannot silently grow
into an unrelated state store.

## 6. Supervisor state machine

```text
missing checkpoint
      │
      ▼
pending ──create Agent──> running ──public result: completed──> completed
                              │
                              ├─retryable failure──> retry_wait
                              │                         │
                              │                         └─Scheduler.wait──> running
                              │
                              └─terminal failure──> failed

loaded retry_wait ──wait remaining delay──> running
loaded running ──safe-boundary resume──> running
```

For each attempt Supervisor:

1. loads or initializes execution state and persists the next attempt before
   constructing the Agent;
2. creates one public Agent through `agent_factory`;
3. restores the saved public session id when present;
4. subscribes to the public event stream;
5. invokes `run(goal.prompt)` and evaluates only the public result;
6. unsubscribes and closes the Agent;
7. persists `completed`, `retry_wait`, `failed`, or `cancelled` state;
8. waits through `Scheduler` before a permitted retry.

If a process dies after a `running` checkpoint, the next invocation resumes at
the safe attempt boundary by restoring the session and issuing the goal again;
the checkpoint never pretends to contain an in-flight Agent runtime snapshot.

## 7. Architecture and deletion guards

- Kernel event modules remain dependency-free; Supervisor imports only public
  Core event contracts.
- Supervisor must not import `lion_code.agent` or
  `lion_code.runtime`, or reference private Agent attributes.
- Agent, profiles and Composition Root must contain zero Supervisor imports,
  fields or construction branches.
- Production Supervisor imports no removed project-state, dream or learning
  module; a focused negative scan covers the full new module.
- Old Autonomy/side-query modules and their direct tests are removed or
  rewritten against the new public Supervisor contract.

## 8. Rollback

The whole Supervisor change is one rollback point. Reverting it restores the
post-PR9 state with no session JSONL format change and no migration. The
existing canonical session history remains untouched; only the new execution
control checkpoint files are removed with the new code.
