# Current Permission Ownership

## Mutable state and mirrors

- `lion_code/agent.py:142,187` stores `permission_mode` and `_confirmed_paths` on Agent.
- `lion_code/agent.py:218-232` copies both values/references into ToolContext.
- `lion_code/agent.py:606-629,1102-1114,1214-1302` repeatedly writes Agent mode and then synchronizes ToolContext.
- `lion_code/session_lifecycle.py:55-84` reads Agent mode and synchronizes Plan path during clear.
- `lion_code/tooling/context.py:40-67` stores permission mode and confirmation cache beside unrelated environment, Plan, execution, Hook and freshness dependencies.

## Consumers and writers

- `lion_code/tooling/middleware.py:102-177` reads mode/path/cache and directly adds confirmation values.
- `lion_code/application/session.py:99-102` and `lion_code/tui/app.py:812` expose the Agent field as frontend state.
- `lion_code/subagent_factory.py:14-24,61-78` asks the Agent host for a child mode at child construction time.
- `lion_code/session_memory_coordinator.py:48-63,406` reads Plan mode while building handoff state.
- `lion_code/agent_runtime.py:250-269` models permission as a writable Session host field.
- `tests/tooling/test_skill_registry_view.py:126-165` mutates Agent.permission_mode directly to simulate live child construction.

## Current semantics to preserve

- Valid modes are `default`, `acceptEdits`, `bypassPermissions`, `dontAsk`, `plan`, and `auto` (`lion_code/__main__.py:54-64`).
- Explicit deny and Plan hard boundaries precede mode-specific policy (`lion_code/tooling/permission.py:151-241`).
- Default-mode confirmations are cached; Auto classifier confirmations are not (`lion_code/tooling/middleware.py:160-175`).
- Cached keys are not only paths: they can be tool reasons or command strings, so `_confirmed_paths` is not an accurate domain name.
- Child agents inherit `plan`/`auto`; all other parent modes become `bypassPermissions` (`lion_code/agent.py:978-988`).
- Plan enter/exit/approval writes mode in two Agent paths and must keep behavior until PlanRuntime owns the transaction.

## Existing regression coverage

- `tests/tooling/test_permission_policy.py` covers explicit deny, Plan hard boundaries and the Plan-file exception.
- `tests/tooling/test_permission_middleware.py` covers deny, Plan blocking and one-time confirmation cache.
- `tests/integration/test_agent_core_runtime.py:714-775` covers clear-and-execute Plan approval and final permission mode.
- `tests/tooling/test_skill_registry_view.py` covers live API/mode reads during child construction.
- `tests/test_hooks.py` covers dontAsk Hook trust behavior.

## Gaps

- No test proves an already-constructed ToolContext observes a mode command without synchronization.
- No architecture rule forbids the current Agent/ToolContext mirror fields or Controller-external writes.
- Auto-mode confirmation non-caching is not paired with the new ownership boundary.
- Direct-assignment tests normalize a mutation pattern the target architecture forbids.
