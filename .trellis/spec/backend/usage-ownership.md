# Usage Ownership

This contract defines the current usage-accounting boundary for one Lion Code
`Agent` session. It is executable architecture, not a migration plan.

## 1. Scope and Trigger

Apply this guide whenever a change reads, records, resets, displays, or limits
model, child-agent, Skill, Dream, response, turn, prompt-window, or cost usage.
It covers `usage.py`, Core event adapters, the Agent composition root,
`AgentRuntimeCoordinator`, `AutonomyRuntime`, session lifecycle, Application,
TUI, and all child execution paths.

The ownership rule is strict:

- One `UsageLedger` owns every mutable usage value for one Agent session.
- One `BudgetPolicy` evaluates frozen Ledger projections.
- `Agent` is the only production composition root for both objects and passes
  those exact instances to the Runtime.
- There is no compatibility layer, migration path, mirror, synchronization
  cursor, fallback total, or second writer.
- `lion_code.core` and `lion_code.providers` remain unaware of Usage ownership.

## 2. Public Signatures and Data Shapes

`lion_code.usage` exposes these frozen read types and single mutable owner:

~~~python
@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    turns: int = 0
    responses: int = 0
    last_prompt_tokens: int = 0
    last_response_at: float | None = None
    cost_usd: float = 0.0
    reported_cost_usd: float = 0.0

@dataclass(frozen=True, slots=True)
class BudgetDecision:
    exceeded: bool
    kind: Literal["max_cost", "max_turns"] | None = None
    reason: str = ""

@dataclass(frozen=True, slots=True)
class BudgetPolicy:
    max_cost_usd: float | None = None
    max_turns: int | None = None
    def check(self, usage: UsageSnapshot) -> BudgetDecision: ...

class UsageLedger:
    def record_model_usage(
        self, usage: Usage, *, response_at: float | None = None
    ) -> None: ...
    def record_child_usage(self, input_tokens: int, output_tokens: int) -> None: ...
    def record_turn(self) -> None: ...
    def reset(self) -> None: ...
    def reset_context_tracking(self) -> None: ...
    def snapshot(self) -> UsageSnapshot: ...
~~~

The external read boundary is `Agent.get_token_usage() -> UsageSnapshot`, then
`LionCodingSession.token_usage() -> UsageSnapshot`. TUI and other frontend
consumers read named snapshot fields; they never receive the Ledger or an
untyped usage dictionary.

`Agent.run()` returns an `AgentRunResult` whose `turns`, input, output, cache
read, and estimated cost are deltas between snapshots taken immediately before
and after that invocation. `Agent.run_once()` returns the same invocation-local
input/output delta in its existing dictionary response. Earlier session usage
must not leak into either result.

## 3. Ownership and Behavioral Contracts

### Model and child aggregation

`UsageObserver` is an event adapter with one reference, `_ledger`. It handles
only terminal `MessageEndEvent` values whose message is `AssistantMessage`, then
calls `record_model_usage()` exactly once. It owns no token, response, timestamp,
cost, or synchronization state.

`record_model_usage()` adds input, output, cache-read, cache-write, reasoning,
and provider-reported cost, increments responses, and replaces the latest prompt
size and response time. `last_prompt_tokens` uses `Usage.total_tokens` when
provided, otherwise input + cache-read + cache-write + output.

Child-agent, Skill, and Dream completion paths call `record_child_usage()`.
That command adds only input and output tokens. It must preserve cache fields,
reasoning, provider-reported cost, responses, turns, `last_prompt_tokens`, and
`last_response_at`; child totals may never overwrite already aggregated parent
usage.

### Cost and budget decisions

Estimated cost is derived from cumulative token totals and is independent of
provider-reported cost:

~~~text
cost_usd = (
    input_tokens * 3
    + cache_read_tokens * 0.3
    + cache_write_tokens * 3.75
    + output_tokens * 15
) / 1_000_000
~~~

`reported_cost_usd` accumulates `Usage.cost.total` separately. `BudgetPolicy`
is stateless: the decision depends only on its frozen limits and the supplied
snapshot. It checks estimated cost before turns, uses inclusive `>=` boundaries,
and returns the existing user-facing reason. When both limits are reached,
`max_cost` wins.

At the Core tool boundary, Runtime must call `record_turn()` before taking the
snapshot and checking the Policy. Therefore the tool call at the exact turn
limit is stopped. Pure final-text responses do not increment turns. Runtime
evaluates the Ledger through the same Policy; the retained Autonomy runtime
(no production caller after PR7a) must not create a second usage budget state
when re-homed. The Coordinator must not pass `BudgetPolicy.max_turns`
to the generic Harness loop: that loop counts provider iterations, including
final-text responses and queued follow-ups, rather than Core tool boundaries.

### Reset and observer lifecycle

Session clear and successful restore call `reset()`: every token field, turn,
response, timestamp, prompt tracker, and reported cost returns to its zero/None
default. Context compaction and Plan clear-and-execute call only
`reset_context_tracking()`, so they clear `last_prompt_tokens` while preserving
all cumulative usage and `last_response_at`.

Terminal-output toggles replace only the terminal renderer. They retain both the
current `UsageObserver` and its Ledger. A full Core-observer rebuild may replace
the adapter, but the replacement must reference the same Ledger. Clear/restore
may rebuild observers and reset that Ledger; they must not replace it.

### Composition and imports

There is exactly one production `UsageLedger()` construction and one production
`BudgetPolicy()` construction, both in `Agent.__init__`. Tests may construct
isolated instances. Ledger fields are private and may be assigned, deleted, or
mutated only inside `lion_code/usage.py`; all other production writers use its
commands.

Core emits canonical usage in Assistant messages but must not import
`lion_code.usage` or observers. Providers construct Core `Usage` data and must
not import runtime ownership modules. Observers may depend on Core events and
Usage. Runtime and Autonomy may depend on Usage. Application imports
`UsageSnapshot` only for its typed projection, and TUI reads that projection
through Application rather than importing the Ledger.

## 4. Validation and Error Matrix

| Boundary | Required behavior | Rejected behavior |
|----------|-------------------|-------------------|
| Model completion | One terminal assistant event records one response | Streaming chunks or non-assistant events mutate totals |
| Child / Skill / Dream | Add child input/output to cumulative totals | Assignment replaces parent totals or changes response/context fields |
| Estimated cost | Use the fixed token formula | Use provider-reported cost as the budget estimate |
| Equal cost and turn limits | Stop on `>=`; cost decision first | Use `>` or return turn when both limits are reached |
| Core tool boundary | Record turn, then check | Check before recording the boundary turn |
| `run` / `run_once` | Return current-invocation deltas | Return whole-session cumulative usage |
| Context compaction / Plan reset | Clear only latest prompt tracking | Clear cumulative usage or response timestamp |
| Session clear / restore | Reset every Ledger field | Preserve stale totals or replace the Ledger object |
| Terminal toggle | Preserve observer and Ledger identity | Rebuild UsageObserver while switching renderer |
| Full observer rebuild | New adapter, same Ledger | New Ledger or copied totals |
| Application / TUI | Frozen typed snapshot | Mutable Ledger or ad-hoc dict crosses the boundary |
| Core / Provider imports | Core data only | Reverse import into Usage or observers |

Commands currently accept the numeric values emitted by trusted Provider and
child runtime paths; input-domain validation is not duplicated in the Ledger.
No API should catch an ownership violation and silently fall back to old Agent
counters, observer totals, or a second cost calculation.

## 5. Good, Base, and Bad Cases

Good aggregation: a parent terminal response records 10 input and 4 output,
then a child returns 3 input and 2 output. The snapshot reports 13 input and 6
output while responses, turns, latest prompt, and response time still describe
the parent path.

Base session: a new or fully reset Ledger returns `UsageSnapshot()` exactly.
Snapshots are immutable values and remain unchanged after later Ledger writes.

Good boundary timing: with `max_turns=1`, Runtime records the first tool turn,
checks a snapshot whose turns equal one, and stops before tool execution. With
both exact cost and turn limits reached, the decision kind is `max_cost`.

Good context transition: compaction or Plan clear-and-execute changes only
`last_prompt_tokens` to zero. The next model response continues cumulative
tokens, responses, turns, and cost from the same Ledger.

Bad ownership: aliasing `UsageLedger` as `Ledger`, assigning it to `Owner`, and
constructing `Owner()` outside the Agent composition root is still a duplicate
owner. Calling `object.__setattr__`, an imported/assigned `setattr` alias, a
bound `__setattr__`, `delattr`, or direct augmented assignment against Ledger
state outside `usage.py` is still a forbidden mutation.

Bad lifecycle: copying observer totals into Agent fields during clear, restore,
or terminal toggles recreates split ownership even if visible totals happen to
match in a happy-path test.

## 6. Tests and Executable Enforcement

The minimum focused matrix is:

- `tests/test_usage.py`: frozen snapshots, model/child aggregation, cost formula,
  reset distinctions, stateless Policy, exact boundaries, and cost priority.
- `tests/runtime/test_usage_observer.py`: event filtering and one-time forwarding
  without observer-owned totals.
- `tests/runtime/test_agent_runtime.py`: turn-before-check timing and shared
  Runtime Ledger/Policy behavior.
- `tests/test_agent_run.py`: `run()` and `run_once()` deltas with pre-existing
  nonzero Ledger state.
- `tests/integration/test_agent_core_runtime.py`: clear/restore full reset,
  compaction/Plan tracking reset, observer rebuild identity, and shared owner.
- `tests/integration/test_application_coding_session.py`: typed snapshot boundary and
  terminal-toggle observer identity.
- child, Skill, Dream, goal, and loop suites: cumulative aggregation and common
  budget decisions.
- `tests/architecture/test_runtime_boundaries.py`: unique construction,
  forbidden legacy names, private-field writes, observer shape, child command
  routing, reverse imports, and scanner self-tests including import aliases,
  assignment aliases, and dynamic/bound mutation bypasses.

Required gates for a Usage ownership change:

~~~powershell
python -m pytest -q tests/test_usage.py tests/runtime/test_usage_observer.py
python -m pytest -q tests/architecture/test_runtime_boundaries.py
python -m pytest -q
ruff check .
ruff format --check .
mypy lion_code tests
python -m compileall -q lion_code tests scripts
lint-imports --no-cache
python ./.trellis/scripts/task.py validate 08-09-usage-ownership
~~~

Repository baseline wrappers may replace raw Ruff or mypy commands where
documented. This ownership move adds no third-party dependency. Any architecture
exception must update code, this contract, its scanner, and a scanner self-test
together; broad allowlists are forbidden.

## 7. Wrong and Correct Patterns

Wrong: expose `Agent.input_tokens`, retain observer totals, and synchronize them
after each Core run. Correct: record the canonical event directly into the one
Ledger and expose a frozen snapshot.

Wrong: `parent_input = child_input`. Correct:
`ledger.record_child_usage(child_input, child_output)`.

Wrong: `if usage.turns > max_turns` or check before incrementing. Correct:
`record_turn()` followed by `policy.check(ledger.snapshot())`, with inclusive
cost-first decisions.

Wrong: call `reset()` after compaction or Plan clear-and-execute. Correct: call
`reset_context_tracking()` and preserve cumulative accounting.

Wrong: rebuild UsageObserver when terminal display changes. Correct: subscribe
or unsubscribe only the terminal renderer and preserve observer identity.

Wrong: hand a Ledger or dictionary to TUI. Correct: Application returns
`UsageSnapshot`, and TUI renders its named fields.

Wrong: hide a second constructor or Ledger write behind an alias or dynamic
setter. Correct: construct only in Agent and mutate only through Ledger commands.
