# Implementation Plan: Application Ports Refactor

## Ordered checklist

1. [x] Audit `LionCodingSession`, `LionAgentRuntime`, `Agent`, composition
   roots, tests, and existing architecture guards.
2. [x] Define the consumer-owned protocols and protocol-neutral
   `QueueSnapshot`.
3. [x] Add semantic Agent/runtime facades without changing the Agent loop or
   Core Harness.
4. [x] Migrate `LionCodingSession` to `_backend` and keep settled/overflow
   retry policy in the application layer.
5. [x] Add `FakeCodingSessionBackend` application tests and move real Agent
   coverage to the integration scope.
6. [x] Add executable import, attribute, TUI, runtime reverse-import, and Fake
   injection guards.
7. [x] Synchronize runtime/TUI boundary specs and run the quality gates.

## Validation matrix

```text
python -m pytest -q tests/application tests/architecture
python -m pytest -q tests/integration tests/tui
python -m compileall -q lion_code tests
ruff check <changed scope>
mypy lion_code
lint-imports --no-cache
python -m pytest -q --durations=20
git diff --check
```

## Results

- Focused application/architecture tests: passed.
- Integration/TUI tests: passed; one POSIX terminal test skipped by platform.
- Full pytest: 704 passed, 6 skipped, 20 subtests passed.
- `compileall`: passed.
- Changed-scope Ruff: passed.
- Import-linter: 6 contracts kept, 0 broken.
- Full Ruff and mypy still report pre-existing repository-wide diagnostics;
  see the final task handoff for the exact gate status.

## Risk points checked

- `_drive` still drains the event queue before settled.
- Overflow compaction retries at most once and checks cancellation before
  `continue_()`.
- Provider configuration no longer rebinds a cached runtime in application.
- Existing `.claude`, `.codex`, `.trellis`, and `AGENTS.md` dirty WIP remains
  outside the task commit scope.
