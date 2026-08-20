# Directory Structure

> The current Lion Code production package is a Python coding-agent runtime, not
> an HTTP backend.  It has no `routes/`, `controllers/`, or generic `services/`
> directory; do not create those abstractions for a feature that belongs to an
> existing runtime layer.

## Production layout

```text
lion_code/
├── __init__.py          # Profile/MetaAgent/Capability/Supervisor public API
├── __main__.py          # CLI / REPL process boundary
├── meta_agent.py        # Feature-neutral public Agent facade
├── adapters/             # Product adapters over feature-neutral facades
├── composition/         # Profiles, object graph root, and Full product bootstrap
│   └── full_product.py  # Full product bootstrap over build_agent_composition
├── core/                # Canonical messages, events, loop and generic Harness
├── runtime/             # Agent Runtime: single-session lifecycle coordination
│   ├── agent.py         # AgentRuntime (operation orchestration only)
│   ├── conversation.py  # ConversationRuntime (Harness/active messages/live provider)
│   ├── session.py       # SessionRuntime (identity/repository/recorder)
│   ├── context.py       # ContextRuntime (context/compaction state)
│   ├── execution.py     # ExecutionControl (cancellation commands)
│   ├── session_identity.py   # SessionIdentityState / SessionView
│   └── provider.py      # ProviderController / ProviderState
├── capabilities/        # Generic SPI plus cohesive built-in feature packages
│   ├── plan/             # Plan capability and runtime
│   ├── skill/            # Skill capability, runtime, and discovery
│   └── subagent/         # SubAgent capability, factory, runtime, and types
├── tooling/             # Tool definitions, registry, permissions and middleware
├── context/             # Provider-context preparation and compaction policy
├── session_runtime/     # Canonical JSONL repository and recorder
├── providers/           # Anthropic and OpenAI-compatible HTTP providers
├── application/         # LionCodingSession and frontend-facing ports
├── supervisor.py        # Agent-external goal/retry/scheduler/checkpoint plane
└── tui/                 # Textual interface
```

Other root modules such as `hooks.py` remain standalone process/runtime
boundaries. Feature-specific implementation belongs in its corresponding
`capabilities/<feature>/` package; do not recreate a root feature module merely
to provide a shorter import path.

## Placement rules

- Put protocol-neutral message, event, provider, tool, and JSONL primitives in
  `lion_code/core/`.  `lion_code/core/messages.py` defines the strict canonical
  wire models; `lion_code/core/session/` owns entry serialization and replay.
- Put use-case orchestration that bridges the Agent and a frontend in
  `lion_code/application/`.  `lion_code/application/session.py` turns Agent
  events into `LionSessionEvent` values; `application/commands.py` owns slash
  command parsing and dispatch.
- Put Agent object-graph construction and the Full product bootstrap in
  `lion_code/composition/`. The builder owns concrete runtime wiring and
  Profile-selected capability registration; `full_product.py` owns the
  application/TUI product factory and reuses that builder. `meta_agent.py` is
  the feature-neutral public facade. Product-specific frontend delegation
  belongs in `adapters/`, whose modules implement adapters only. The composition
  result is explicit and one-shot: no builder, container, or service locator is
  retained by runtime or domain modules.
- Put built-in feature implementations in their cohesive package under
  `lion_code/capabilities/`; generic SPI files (`types.py`, `registry.py`, and
  `runtime.py`) must not import a concrete feature.
- Put provider-specific HTTP/request/stream handling in `lion_code/providers/`.
  `providers/factory.py`, `providers/anthropic.py`, and
  `providers/openai_compatible.py` are the current protocol boundary.
- Put all tool execution policy in `lion_code/tooling/`; a new tool should use
  the registry/runtime path rather than add a second execution loop.  See
  `tooling/runtime.py`, `tooling/middleware.py`, and `tooling/builtin.py`.
- Put durable-session coordination in `lion_code/session_runtime/`.  The
  repository locates/replays JSONL, while the recorder appends entries.  Do not
  make the TUI or a provider write session files directly.
- Put Textual widgets, state and rendering in `lion_code/tui/`; non-Textual
  terminal event rendering belongs in `lion_code/observers/terminal.py`.
- Put autonomous goal, scheduler, retry and checkpoint control only in
  `supervisor.py`. Supervisor consumes an `AgentFactory` returning the public
  `AgentPort`; Profiles, MetaAgent, Kernel, Harness and Capabilities do not know
  that Supervisor exists.
- There is no catch-all `utils/` package.  Keep a helper private to its owning
  module unless it has a clear runtime boundary; then place it in the matching
  package rather than creating an unowned utility bucket.

## Naming and source conventions

- Python modules and tests use `snake_case`; public classes use `PascalCase`.
  Examples include `SessionRepository`, `JsonlSessionStorage`, and
  `test_agent_core_runtime.py`.
- New package tests normally mirror their source package under `tests/`, for
  example `lion_code/session_runtime/` -> `tests/session_runtime/` and
  `lion_code/tui/` -> `tests/tui/`.  Existing root modules may use a matching
  `tests/test_<module>.py` file.
- Match the local module's typing style.  Current package modules commonly use
  `from __future__ import annotations`, explicit return types, and small
  single-purpose classes/functions.
- Follow `AGENTS.md`: express ordinary flow through names, types and function
  boundaries; source comments explain rationale, invariants, compatibility,
  performance or safety constraints and are written in Chinese.  Public APIs
  document their contract, boundary, side effects and exceptions.  Temporary
  work uses `TODO(issue): reason and completion condition`.

## Representative examples

| Concern | Current example |
|---|---|
| Public product API | `lion_code/__init__.py` exports Profiles, `MetaAgent`, `CapabilitySpec`, and Supervisor ports. |
| Process boundary | `lion_code/__main__.py` parses CLI options, constructs the internal Full product host, and starts the TUI or REPL. |
| Application bridge | `lion_code/application/session.py::LionCodingSession._drive` subscribes to Agent events and yields application events. |
| Tool execution | `lion_code/tooling/runtime.py::ToolRuntime.execute` resolves a registered tool and runs the middleware chain. |
| Persistence | `lion_code/session_runtime/repository.py::SessionRepository` and `recorder.py::SessionRecorder` split read/replay from append-only writes. |
| Provider boundary | `lion_code/providers/` contains the built-in HTTP protocol implementations rather than provider SDK clients. |

## Avoid

- Do not add HTTP routes, controllers, ORM services, or a generic `utils/`
  directory: none is part of the current architecture.
- Do not let a frontend, provider, or tool bypass `core/`, `tooling/`, or the
  session runtime to own duplicate message state or persistence.
- Do not put Textual rendering in `application/` or terminal `print_*` calls in
  the TUI.  The existing boundaries keep frontends replaceable.
