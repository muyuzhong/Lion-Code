# Directory Structure

> The current Lion Code production package is a Python coding-agent runtime, not
> an HTTP backend.  It has no `routes/`, `controllers/`, or generic `services/`
> directory; do not create those abstractions for a feature that belongs to an
> existing runtime layer.

## Production layout

```text
lion_code/
├── __main__.py          # CLI / REPL entry point and process-level error boundary
├── agent.py             # Agent composition and high-level runtime ownership
├── provider_manager.py  # ProviderState/View and Provider/Thinking commands
├── application/         # LionCodingSession, application events and slash commands
├── core/                # Canonical messages, events, harness, loops and session protocol
├── providers/           # Built-in Anthropic and OpenAI-compatible HTTP providers
├── tooling/             # Tool definitions, registry, permissions and middleware runtime
├── adapters/            # Boundary adapters between Lion tooling and Core tools
├── session_runtime/     # JSONL repository/recorder and legacy JSON read-migration
├── memory_runtime/      # Memory coordination, injection and queries
├── observers/           # Event consumers such as terminal and usage renderers
└── tui/                 # The Textual frontend only
```

Other root modules such as `autonomy.py`, `dream.py`, `hooks.py`, `memory.py`,
`skills.py`, and `tools.py` are existing feature modules.  Keep a change close
to its current owner instead of moving it merely to make a generic layered
diagram look cleaner.

## Placement rules

- Put protocol-neutral message, event, provider, tool, and JSONL primitives in
  `lion_code/core/`.  `lion_code/core/messages.py` defines the strict canonical
  wire models; `lion_code/core/session/` owns entry serialization and replay.
- Put use-case orchestration that bridges the Agent and a frontend in
  `lion_code/application/`.  `lion_code/application/session.py` turns Agent
  events into `LionSessionEvent` values; `application/commands.py` owns slash
  command parsing and dispatch.
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
| Process boundary | `lion_code/__main__.py` parses CLI options, constructs `Agent`, and starts the TUI or REPL. |
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
