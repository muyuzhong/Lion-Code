# Four-Layer Ownership

This is the current ownership map after PR9. It documents executable boundaries,
not historical implementation or future Memory design.

## Ownership map

| Layer | Current owners | Must not own |
| --- | --- | --- |
| Kernel | `core/`, `context/`, `session_runtime/`, `provider_manager.py`, `execution_control.py`, `permission_state.py`, `usage.py` | Product capabilities, frontend state, project feature stores |
| Harness | `agent_runtime.py`, `session_lifecycle.py`, `composition/`, `agent.py` | A second history, service locator, or deleted legacy graph |
| Capability | `capabilities/`, `plan_runtime.py`, `skill_runtime.py`, `subagent_factory.py`, `subagent_runtime.py` | Provider/session ownership, broad Agent dependencies, Memory/Dream/Learning replacements |
| Application/Supervisor | `application/`, `tui/`, `supervisor.py` | Core/Harness containers, direct JSONL writes, Agent private runtime, removed command surfaces |

`CapabilityRegistry` aggregates immutable contributions and closeable resources;
it is not a service locator. `ContextManager` and `ContextCompactor` remain
Kernel context policy and are the only generic provider-context preparation path.

## Current composition

`MinimalProfile` constructs an empty CapabilityRegistry. `CodingProfile` can add
Skill/SubAgent through the existing Skill composition. `FullProfile` registers
Plan, SubAgent, Skill, and caller extension specs. No Profile creates or names a
Memory, Dream, Learning, Null, Deprecated, Legacy, or fallback object.

## Canonical session ownership

`SessionRepository` replays JSONL, `SessionRecorder` appends Core events, and
`SessionLifecycle` coordinates clear/restore/compact transitions. The canonical
compaction entry model at `core/session/memory.py` is retained. It must not be
confused with the removed project-level Memory files or repositories.

Application code consumes semantic ports from `application/ports.py`. It owns
frontend event bridging and overflow retry policy; it does not inspect Harness
queues or cache Core runtime objects. TUI code reaches the runtime through the
application session.

## Deleted boundary

PR9 removed the old project Memory package and coordinator, Dream modules and
adapter, Learning runtime, Memory-only provider text query, Memory file-write
hook, project Memory facade/application ports, and the Memory-only per-request
capability projection slot. No compatibility alias or placeholder remains.

The Supervisor consumes only the public Agent event/result/session contracts.
Goal lifecycle, scheduler, retry/recovery and execution-control checkpoints are
owned by `supervisor.py`; Provider request retry, UsageLedger/BudgetPolicy,
canonical session replay and Application overflow retry remain with their
existing owners. Skill, Plan, SubAgent, Provider, permission, Event Stream and
context compaction remain active ownership contracts.

## Architecture tests

`tests/architecture/test_legacy_memory_removal.py` checks exact removed modules
and symbols, while explicitly allowing generic `memory` terminology and
`core/session/memory.py`. Other architecture tests cover import direction,
composition profiles, zero-extension, capability lifecycle, session persistence,
provider ownership, application ports, and TUI/runtime direction.
