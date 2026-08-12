# Implementation Plan

## Ordered checklist

1. Update tooling contracts and context.
   - Add `ToolCommand`.
   - Remove `AgentToolController` and `ToolContext.controller`.
   - Refactor internal capability factories to capture commands; rename the
     wakeup factory so the removed route name is absent from production.
2. Implement independent child execution.
   - Add `SubagentExecutor` with shared agent/Skill-fork lifecycle.
   - Keep `SubagentFactory` construction-only.
   - Preserve status ordering, permission inheritance, usage aggregation, error
     text, and child closure.
3. Implement `SkillRuntime`.
   - Move lookup, inline, unknown, and fork behavior out of `Agent`.
   - Delegate fork lifecycle to `SubagentExecutor`.
4. Add direct capability bindings.
   - Update Skill and Subagent capabilities to receive their runtime/executor.
   - Add Plan ToolSource capability bound to `PlanRuntime`.
   - Bind dynamic wakeup directly to `AutonomyRuntime`.
5. Rewire Agent composition.
   - Construct dependencies in an order that includes deferred Plan tools in
     prompt metadata.
   - Remove the old Agent tool methods and private execution implementations,
     plus dead imports/wrappers.
6. Update focused behavior tests and add architecture tests.
   - Replace old controller-based fixtures with command-bound tools.
   - Move old Agent private-method tests to executor/runtime/tool tests.
   - Add explicit assertions for all requested acceptance behaviors.
7. Run quality gates and fix only regressions caused by this scope.

## Validation commands

Focused iteration:

```powershell
python -m pytest -q tests/tooling/test_internal_tools.py tests/tooling/test_runtime.py tests/tooling/test_agent_runtime.py tests/tooling/test_skill_registry_view.py tests/capabilities/test_capability_migration.py tests/test_plan_runtime.py tests/test_autonomy_flow.py tests/test_autonomy_goal_loop.py
python -m pytest -q tests/architecture/test_tool_routing.py tests/architecture/test_runtime_boundaries.py
```

Full matrix:

```powershell
python -m pytest -q
python -m compileall -q lion_code tests scripts
lint-imports --no-cache
python -m ruff check lion_code tests scripts
python -m ruff format --check lion_code tests scripts
python -m mypy lion_code --platform linux -O json
git diff --check
```

Also run a production-only search for every removed route string:

```powershell
rg -n --glob '!tests/**' --glob '!\.trellis/**' --glob '!\.claude/**' "AgentToolController|context\.controller|run_skill_tool|run_subagent_tool|enter_plan_mode_tool|exit_plan_mode_tool|schedule_wakeup_tool" lion_code
```

## Review gates

- Before editing source, verify every current constructor/caller found during
  planning and preserve unrelated dirty `.claude` files.
- After each implementation slice, run its focused tests and `git diff --check`.
- Before activation, confirm no Provider/Memory/PromptComposer/AgentBuilder
  files were changed.
- Before commit, inspect `git diff --stat`, `git diff --name-only`, and staged
  paths; stage only the scoped source, tests, and Trellis task artifacts.
- Commit once with a Chinese description after all checks pass, as required by
  `AGENTS.md`.

## Risk and rollback points

- Composition-order changes can omit deferred Plan tools from system prompt
  metadata. Verify registry contents and dynamic context before/after Plan
  initialization.
- Moving old Agent tests to direct runtime tests can accidentally bypass
  middleware. Every behavior test must execute through `ToolRuntime` where the
  production tool path does.
- Child errors can lose end status or close behavior when construction fails.
  Use explicit event-order assertions and a child fixture with failing
  `run_once`.
- Existing dirty `.claude` changes must never be included in the refactor
  commit. If scope cannot be isolated, stop before staging.
