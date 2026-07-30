# Quality Guidelines

> Match the repository's current Python/runtime conventions and verify behavior
> through its existing tests.  Do not add invented formatter, type-checker, or CI
> requirements: the committed `pyproject.toml` contains packaging/runtime settings
> but no project configuration for Ruff, Black, mypy, or a test runner.

## Source standards from `AGENTS.md`

- Prefer precise names, types and function boundaries over comments that narrate
  obvious code.
- Comments explain rationale, business-rule origin, invariants, compatibility,
  performance or security constraints.  Source comments are Chinese; identifiers
  and necessary technical terms remain English.
- Public API documentation states the contract, boundary, side effects and
  exceptions.  Keep private implementation comments only when they add that
  non-obvious context.
- Update or remove comments together with the implementation.  Use only
  `TODO(issue): reason and completion condition` for temporary work.

## Current implementation and test patterns

- New code is typed and commonly starts with `from __future__ import annotations`.
  Pydantic wire models in `lion_code/core/messages.py` use `extra="forbid"` and
  camel-case serialization aliases so persisted/provider payloads stay strict.
- Async behavior is tested with `unittest.IsolatedAsyncioTestCase`; synchronous
  behavior uses `unittest.TestCase`.  See `tests/tooling/test_mcp_adapter.py`,
  `tests/integration/test_core_tool_runtime.py`, and
  `tests/runtime/test_terminal_renderer.py`.
- Tests isolate external effects with `unittest.mock` and project fakes.  Provider
  integration tests inject `FakeProvider` rather than call a real OpenAI or
  Anthropic endpoint.
- Test directories normally mirror production packages: `tests/application/`,
  `tests/core/`, `tests/providers/`, `tests/session_runtime/`, `tests/tooling/`,
  and `tests/tui/`.

## Required validation for a change

- Add or update the smallest focused test that proves the changed contract,
  including error/cancellation or persistence cases when the changed boundary has
  them.
- Run the documented repository checks appropriate to the edit:

  ```powershell
  python -m pytest -q
  python -m compileall -q lion_code tests
  ```

- For a focused iteration, run the affected test file first, then the full suite
  before declaring the task complete.  `README.md` lists the separate formal
  context-management benchmark; run it only when its code/data changes.
- Run `git diff --check` before handoff.  The project instruction requires each
  completed change to use a Chinese commit description, but task-specific handoff
  instructions may intentionally reserve committing for the parent workflow.

## Review checklist

- Does the change stay in the existing layer boundary rather than add a duplicate
  provider, message history, tool execution path, or session writer?
- Are expected tool/provider/persistence failures represented through the current
  structured error/event contracts and covered by tests?
- Does a persistence change preserve append/replay and legacy read-only behavior?
- Does UI-facing work preserve the event/observer ownership contracts instead of
  adding stdout capture or global callbacks?
- Are comments, public docstrings, tests and README/spec statements still true of
  the implementation?

## Avoid

- Do not call real provider APIs in normal unit/integration tests when the
  repository has `FakeProvider` and mocks for deterministic coverage.
- Do not weaken strict Core wire models with unvalidated dictionaries or allow
  unknown persisted fields merely to make a test pass.
- Do not claim a required linter/type checker or CI gate that is not committed in
  the repository.  Add such tooling only as an explicit, separately reviewed
  change.
