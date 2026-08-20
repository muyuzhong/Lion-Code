# Implementation Plan

## Ordered work

1. Extend the generic Capability SPI.
   - Add the documented `ContextLayer` Protocol and nullable
     `CapabilitySpec.context_layer` field.
   - Add `CapabilityRegistry.context_layers` aggregation and export the public
     protocol from the generic capability package as appropriate.
   - Update capability SPI tests for old construction, aggregation, and empty
     registry behavior.

2. Add immutable ContextView projection types.
   - Define frozen/slots utilization, tool-trace, and ContextView values.
   - Implement deterministic tool argument summaries and the last-three failure
     summaries without mutating or retaining message/container references.
   - Export the types from `lion_code.context` and add direct projection tests.

3. Extend ContextManager through the existing prepare hook.
   - Add an optional structural context-layer callback with an empty default.
   - Preserve the current projection operations and action ordering.
   - Render stable-sorted non-empty layers at the final step into one transient
     UserMessage, and include it in final prepared token estimation.
   - Add tests for wrapper/role/tail placement, sorting, no-layer exactness, and
     source-message immutability.

4. Implement built-in ContextLayer packages.
   - Add stateless AgentStateLayer and GitStatusLayer capability packages.
   - Add PlanContextLayer to the existing Plan CapabilitySpec for the Task row.
   - Keep AgentStateLayer unaware of Plan and keep Git status reads uncached.

5. Wire Composition without Runtime changes.
   - Register built-in state/workspace specs for Coding and Full selections.
   - Pass the CapabilityRegistry context-layer callback to the default
     ContextManager.
   - Preserve caller extension specs for every Profile and the Minimal no-layer
     baseline.

6. Add cross-layer integration and architecture coverage.
   - Capture provider request messages and assert transient-only behavior across
     canonical messages, JSONL recorder, CompactionEntry, and compactor input.
   - Extend reachable-object-graph checks for a ContextLayer-bearing Profile and
     verify no new mutable owner is reachable from AgentRuntime, SessionRuntime,
     CapabilityRuntime, or SubagentFactory.
   - Verify removing the new specs leaves the feature-neutral graph runnable.

7. Run focused checks, then the full quality matrix; distinguish any existing
   dirty-worktree or baseline failures from this change.

## Validation commands

Focused first:

```powershell
python -m compileall -q lion_code tests
python -m pytest -q tests/capabilities/test_capability_registry.py tests/context/test_projector.py tests/architecture/test_runtime_ownership.py tests/architecture/test_composition_profiles.py
python -m pytest -q tests/context tests/capabilities tests/integration/test_agent_core_runtime.py tests/integration/test_meta_agent.py
git diff --check
```

Repository quality gates, using the repository's configured commands and
baseline where applicable:

```powershell
python -m pytest -q
python -m compileall -q lion_code tests
python -m ruff check lion_code tests scripts --output-format=json > ruff.json
python scripts/check_quality_baseline.py ruff-check ruff.json --status 1 --baseline docs/quality-baseline-2026-08.json
```

Also run the configured mypy, import-linter, coverage, ruff-format, radon, and
vulture checks from `.github/workflows/ci.yml`; report missing local tools or
pre-existing baseline fingerprints separately rather than masking them.

## Review gates before activation

- `prd.md`, `design.md`, and this file have no unresolved blocking product
  decisions.
- `implement.jsonl` and `check.jsonl` contain real spec entries.
- No implementation change touches the explicitly forbidden Runtime files or
  `meta_agent.py`.
- The user explicitly approves this final planning summary before
  `task.py start`.

## Rollback points

- Before code edits: task artifacts only; no product behavior changed.
- After SPI/ContextManager edits: revert the single work commit if projection
  compatibility fails.
- After built-in wiring/tests: remove only the new capability packages and
  Composition registrations to return to the generic no-layer path.
