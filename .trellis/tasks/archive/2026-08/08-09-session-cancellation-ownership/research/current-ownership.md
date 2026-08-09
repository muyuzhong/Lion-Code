# Current Session and Cancellation Ownership

## Session identity

- `lion_code/agent.py:160-161` creates mutable `session_id` and `session_start_time` on Agent.
- `lion_code/agent.py:214-227` copies `session_id` into ToolContext and wraps `_aborted` in `cancellation_fn`.
- `lion_code/session_lifecycle.py:67-69` writes a new Agent identity and then manually mirrors the ID to ToolContext.
- `lion_code/session_lifecycle.py:102-103` repeats the same two writes during restore.
- `lion_code/agent_runtime.py:245-259` exposes writable session identity through `SessionStateHost`.
- `lion_code/core/session/memory.py:22-75` already uses `SessionState` for an immutable JSONL replay result, so the active identity state needs a distinct name.

## Cancellation

- `lion_code/agent.py:177,227,378-381` stores `_aborted`, exposes it as a property, and closes ToolContext over it with a lambda.
- `lion_code/agent_runtime.py:757-774` writes `_aborted` during abort and resets it at chat start.
- `lion_code/agent_runtime.py:641-650,784-867` reads or writes `_aborted` in compaction, chat and timeout paths.
- `lion_code/autonomy_runtime.py:41-49,127-336`, `lion_code/session_memory_coordinator.py:48-52,366` and `lion_code/__main__.py:116` consume the host field directly.
- `lion_code/core/provider.py:13-16` and `lion_code/core/tools.py:15-18` define duplicate read protocols.
- `lion_code/core/harness.py:61-72,94-135` owns a private per-run token.
- `lion_code/adapters/tool_adapter.py:38-75` converts the Core signal back into a callback for ToolRuntime.
- `lion_code/tooling/runtime.py:27-93` combines cancellation callbacks with a lambda and replaces ToolContext for one execution.

## Existing regression coverage

- `tests/core/test_cancellation.py` covers Harness cancellation between turns and aborted provider events.
- `tests/integration/test_agent_core_runtime.py:506-538` covers Agent abort followed by a successful later chat.
- `tests/runtime/test_agent_runtime.py:188-225` covers runtime cancellation propagation.
- `tests/application/test_coding_session.py` covers application-session cancel behavior.
- `tests/integration/test_agent_core_runtime.py:540-585` covers restore and clear behavior.

## Constraints

- Core cannot import tooling/application/TUI; shared cancellation primitives must live in Core or below.
- Tooling may consume Core contracts.
- SessionRecorder remains the only active JSONL writer.
- No compatibility parameters or fallback fields are permitted by project rules.
