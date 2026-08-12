# Remove Agent Business Routing from Internal Tool Execution

## Goal

Remove the internal tool execution route
`ToolContext.controller -> AgentToolController -> Agent` from Lion Code.
Each capability-specific tool must capture its domain command or runtime at
construction time while preserving the existing `LionTool.execute_fn` shape,
middleware pipeline, state ownership, and observable tool behavior.

## Background and Confirmed Facts

- `ToolContext` currently stores `controller: AgentToolController`.
- `lion_code/tooling/internal.py` routes the `agent`, `skill`, Plan, and dynamic
  `schedule_wakeup` tools through `context.controller`.
- `Agent` currently owns the public tool delegates and the private
  `_execute_skill_tool` and `_execute_agent_tool` implementations.
- Skill and Subagent capabilities already contribute tools through `ToolSource`,
  but their factories create unbound tools whose execution still reaches Agent.
- `PlanRuntime` owns Plan state and permission transitions.
- `AutonomyRuntime` owns dynamic loop wakeup state and validation.
- `SubagentFactory` already owns child construction and permission/tool
  selection; it must remain construction-only.
- The existing middleware and `ToolRuntime` must remain the single execution
  pipeline and must continue converting expected execution failures to
  structured `ToolResult` values.

## Requirements

1. Delete `AgentToolController` and remove `ToolContext.controller`.
2. Add the smallest command contract needed for capability-bound tools:
   `async __call__(arguments: Mapping[str, JSONValue]) -> ToolResult`.
   Keep the unified `LionTool.execute_fn` signature unchanged; capability tools
   may ignore `ToolContext`.
3. Add an independent `SkillRuntime` that owns skill lookup, inline skill
   behavior, fork skill behavior, and unknown-skill handling. It must not
   receive or import `Agent`.
4. Add a `SubagentExecutor` / `SubagentRuntime` boundary that owns child
   construction through `SubagentFactory`, start/end status, `run_once`, child
   usage aggregation, expected error conversion, and `finally`-based child
   closure. Skill forks must reuse this lifecycle service.
5. Change Skill and Subagent capabilities to receive their executor/runtime at
   construction and produce tools already bound to those dependencies.
6. Bind Plan tools directly to `PlanRuntime`; a Plan capability may expose only
   a `ToolSource` in this change. Do not add PromptLayer or SessionParticipant.
7. Bind the dynamic `schedule_wakeup` tool directly to an AutonomyRuntime
   command. It must not route through Agent.
8. Remove obsolete Agent tool routes and private business implementations when
   no production caller remains: `run_skill_tool`, `run_subagent_tool`,
   `enter_plan_mode_tool`, `exit_plan_mode_tool`, `schedule_wakeup_tool`,
   `_execute_skill_tool`, and `_execute_agent_tool`.
9. Capabilities must not import `Agent` or `AgentHarness`; no new generic
   controller, service locator, or broad Agent service interface may be added.
10. Preserve state ownership: Plan state remains owned by `PlanRuntime`, wakeup
    state by `AutonomyRuntime`, usage by the existing `UsageLedger`, and child
    construction by `SubagentFactory`.
11. Add architecture coverage for the removed controller route and capability
    import direction, plus behavior coverage for inline/fork Skill, SubAgent
    success/error, child usage and closure, status start/end, Plan enter/exit,
    dynamic wakeup, permission inheritance, middleware behavior, and
    `ToolResult.terminate` semantics.
12. No Provider, Memory, PromptComposer, or AgentBuilder refactor is in scope.

## Acceptance Criteria

- [ ] Production search finds no `AgentToolController`, `context.controller`,
      `run_skill_tool`, `run_subagent_tool`, `enter_plan_mode_tool`,
      `exit_plan_mode_tool`, or `schedule_wakeup_tool`.
- [ ] `ToolContext` has no controller/service-locator field, and internal
      capability tools execute through their construction-time command/runtime.
- [ ] `SkillRuntime` and `SubagentExecutor` have no dependency on `Agent` or
      `AgentHarness`; capability modules have no such imports.
- [ ] Skill inline and fork behavior, unknown Skill handling, SubAgent success
      and error conversion, status start/end, usage aggregation, and child
      closure are verified by tests.
- [ ] Plan enter/exit, permission inheritance, dynamic wakeup registration and
      removal, middleware behavior, and `terminate` propagation are verified by
      tests.
- [ ] Architecture tests enforce the removed controller route and import
      boundary.
- [ ] `python -m pytest -q`, architecture tests, `lint-imports --no-cache`,
      Ruff, mypy, compileall, and `git diff --check` are run and their exact
      results are reported.
- [ ] Only this scoped refactor and its tests/docs are committed; unrelated
      pre-existing worktree changes remain untouched.

## Out of Scope

- Provider, Memory, PromptComposer, AgentBuilder, or application-port changes.
- New persistence, migration, compatibility layer, fallback controller, or
  generic service container.
- Changes to tool middleware ordering or policy semantics.
