# Goal-Aware Structured Compaction — Technical Design

## 1. Ownership and boundaries

| Module | Change | Ownership preserved |
| --- | --- | --- |
| `lion_code/context/compaction.py` | Add `CompactionRequest`, objective resolution helpers, the single structured prompt template, and update `ContextCompactor` / `ProviderContextCompactor`. | Kernel owns the provider-neutral compaction contract and prompt; it does not own Session or Plan state. |
| `lion_code/runtime/context.py` | Accept the request inputs, resolve the objective through an injected read-only PlanView-compatible source, create `CompactionRequest`, then invoke the compactor. | ContextRuntime remains the only owner of compaction task/cancellation state. No new mutable history or policy state. |
| `lion_code/runtime/agent.py` | Pass the current user message as the active objective and the existing retained suffix as `recent_context`. | AgentRuntime remains orchestration-only; no new state, threshold, boundary, or persistence logic. |
| `lion_code/composition/agent_builder.py` | Pass the existing FullProfile PlanRuntime as a structural read-only PlanView to ContextRuntime; Minimal/Coding paths pass no Plan view. | Composition remains the only graph-wiring location; PlanRuntime remains the Plan owner. |
| `lion_code/context/manager.py`, `policy.py`, `core/session/*`, `session_runtime/*` | No production behavior change. | Projection, policy, canonical history, append-only recording and replay stay intact. |

The small AgentRuntime change is argument plumbing only. It is required because the current
boundary calculation owns both the old prefix and retained suffix, while ContextRuntime owns
the compactor invocation. Moving either ownership would violate the existing runtime map.

## 2. Contract

```python
@dataclass(frozen=True, slots=True)
class CompactionRequest:
    history: tuple[AgentMessage, ...]
    recent_context: tuple[AgentMessage, ...]
    objective: str | None

class ContextCompactor(Protocol):
    async def summarize(self, request: CompactionRequest) -> str: ...
```

`CompactionRequest.__post_init__` normalizes both message collections to tuples. `None` is the
explicit objective-unavailable marker; the prompt renders it as a non-inference marker rather
than allowing the model to invent a goal.

`ContextRuntime.summarize(history, *, recent_context=(), objective=None)` creates the request
immediately before scheduling the existing compaction task. The request is not persisted as a
new entry and no Runtime mutable field stores it.

## 3. Objective resolution

The resolver runs in this order:

1. Use the explicit objective supplied by `AgentRuntime.chat(user_message)` when non-empty.
2. Otherwise use the latest non-empty user message in `recent_context`, then `history`.
3. If the injected PlanView reports `is_active` and its `file_path` exists and can be read,
   append the plan content and path to the resolved objective.
4. If no user objective and no readable active plan exist, return `None`.

Optional Plan reads catch only `OSError` at this boundary and return the empty marker. They do
not create a replacement plan, cache plan content, or hide provider/compaction failures. The
PlanView dependency is structural (`is_active` / `file_path`) so the context contract does not
import the concrete Plan capability package.

## 4. Provider prompt and message projection

`COMPACTION_PROMPT_TEMPLATE` is the only structured compaction template in the compaction
module. The provider compactor:

1. Deep-copies only `request.history` for the model input.
2. Adds one clearly delimited user message containing the objective and a readable rendering
   of `request.recent_context` as background. Recent context is not rewritten or summarized.
3. Adds the fixed output protocol and evidence instructions from the single template.
4. Streams through the existing `ModelProvider` event contract with `tools=[]` and `signal=None`.

The required output headings, in order, are:

```text
# Objective
# Constraints
# Decisions
# Repository State
# Findings
# Failed Attempts
# Completed Work
# Remaining Work
# Verification
```

The template explicitly requires every Findings and Verification item to carry Coding Evidence
such as `file path::symbol`, command/result, commit hash, or a one-line error summary. There is
no separate output validator in this PR; malformed provider output continues to surface as the
existing non-empty-summary/provider error contract.

## 5. Runtime data flow

```text
chat(user_message)
  -> compact_if_needed(objective=user_message)
  -> boundary splits history / retained suffix
  -> ContextRuntime.summarize(history, recent_context, objective)
  -> CompactionRequest(history, recent_context, resolved objective)
  -> ProviderContextCompactor + fixed prompt
  -> SessionRuntime.record_compaction(summary, replaces_entry_ids)
  -> existing SessionState replay
```

Manual compaction passes no explicit objective and uses the latest canonical user message as
fallback. Overflow compaction keeps its existing two-user-boundary suffix and likewise uses the
canonical latest user message because the failed prompt is already in the active history.

## 6. Compatibility and rollback

- The old `summarize(messages)` protocol is intentionally replaced; all in-repository fakes and
  tests migrate to `CompactionRequest` without compatibility aliases.
- `CompactionEntry`, `replaces_entry_ids`, recorder locking, JSONL append order and replay are
  unchanged. A failed/cancelled compactor writes no new entry, as before.
- Rollback is a single coherent code change: revert the compaction contract, request wiring,
  prompt tests and updated fakes together. No migration is needed because persisted summaries
  remain plain text inside the existing CompactionEntry.
