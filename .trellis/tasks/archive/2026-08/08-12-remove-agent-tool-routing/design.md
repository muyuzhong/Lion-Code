# Technical Design

## Boundary

The change is limited to the internal capability-tool construction and
execution path. `Agent` remains the composition root and still owns the
concrete runtimes, registry, middleware, usage ledger, and child factory. It
does not remain the business dispatcher for these tools.

The resulting flow is:

```text
Agent composition root
  ├─ SubagentFactory (construct child only)
  ├─ SubagentExecutor (child lifecycle + status + usage + error + close)
  ├─ SkillRuntime (lookup + inline/fork policy; fork delegates executor)
  ├─ PlanRuntime (Plan state and commands)
  └─ AutonomyRuntime (dynamic wakeup command)
        ↓ construction-time command capture
ToolSource -> LionTool -> ToolRuntime -> unchanged middleware -> command
```

`ToolContext` continues to carry live session, cancellation, registry,
permission, Plan view, read freshness state, confirmation callbacks, hooks and
audit callbacks. It no longer carries a business controller or a replacement
service-locator field.

## Contracts

### Tool command

Add one narrow protocol next to the existing tooling types:

```python
class ToolCommand(Protocol):
    async def __call__(
        self,
        arguments: Mapping[str, JSONValue],
    ) -> ToolResult: ...
```

The existing `ToolExecutor` / `LionTool.execute_fn` signature remains
unchanged. Capability-specific factories wrap a captured `ToolCommand` in that
signature and discard `ToolContext`, call id, and update callback. Built-in,
MCP, search, and other context-sensitive tools keep their current execution
functions.

### SubagentExecutor

Create `lion_code/subagent_runtime.py` with a concrete `SubagentExecutor`.
It receives only:

- `SubagentFactory` for child construction;
- the existing `UsageLedger` for `record_child_usage`;
- a narrow status callback (`agent_type`, description, started flag).

It provides two commands/entry points, one for a configured agent type and one
for a Skill fork. Both share one private lifecycle implementation:

1. emit start status;
2. construct the child through `SubagentFactory`;
3. await `run_once`;
4. merge only child input/output usage;
5. return the existing result text, with empty-output fallback;
6. convert expected child-run failures to `ToolResult(is_error=True)` while
   retaining the current user-facing error prefixes;
7. emit end status and close the child in `finally`.

The executor imports neither `Agent` nor `AgentHarness`. `SubagentFactory`
continues to use its existing construction-time local import solely to create
the child; it gains no run, usage, status, or close responsibility.

### SkillRuntime

Create `lion_code/skill_runtime.py` with `SkillRuntime` receiving a
`SubagentExecutor`. It is itself callable as a `ToolCommand` and owns:

- lookup and prompt resolution using the existing Skill definitions/functions;
- unknown Skill result text;
- inline activation result text;
- fork decision and argument normalization;
- delegation of fork execution to `SubagentExecutor`.

It never receives or imports `Agent`. It does not duplicate child status,
usage, or closure logic.

### Capability ToolSources

- `create_skill_capability(skill_runtime)` creates a ToolSource whose tool is
  created by `create_skill_tool(skill_runtime)`.
- `create_subagent_capability(subagent_executor)` creates a ToolSource whose
  tool is created by `create_agent_tool(subagent_executor)`. The historical
  tool name `agent` remains unchanged.
- Add `capabilities/plan.py` with a ToolSource-only Plan capability. It binds
  `PlanRuntime.enter` and `PlanRuntime.exit` through tiny local commands that
  map `PlanToolOutcome` to `ToolResult`, preserving `terminate`.
- `create_internal_tools()` retains only context-sensitive resident internal
  tools such as `tool_search`. Plan tools are registered through the Plan
  capability so their creation-time dependency is explicit.

The capability modules import only the narrow runtime/concrete dependency they
consume plus tooling/capability types. They do not import `Agent` or
`AgentHarness`, and no new `CapabilityContext`, `AgentServices`,
`GenericToolController`, or `ServiceLocator` is introduced.

### Autonomy wakeup

Rename the factory to `create_wakeup_tool(command)` and bind it to an
`AutonomyRuntime` command (for example `AutonomyRuntime.schedule_wakeup`).
The dynamic loop keeps temporary registration/removal behavior, but the
temporary tool is created with the current runtime command. Remove the Agent
wrapper used only by the old tool route.

## Composition order

The Agent composition root will construct the registry and ToolEnvironment,
then the SubagentFactory and SubagentExecutor, then the PlanRuntime (without
initializing prompt state), then register MCP/Skill/Subagent/Plan capability
tools. It will build the complete system prompt from the now-complete registry,
initialize PlanRuntime, and finally create ToolContext and ToolRuntime.

This preserves the existing deferred-tool prompt list while allowing Plan
tools to be directly bound. The registry remains Agent-instance-local and the
Plan/permission objects remain the same live views exposed to middleware.

## Error and state semantics

- Middleware order and `ToolRuntime` exception conversion are unchanged.
- `ToolResult.terminate` from Plan commands is copied unchanged.
- Child success adds only input/output tokens to the parent's existing ledger;
  it does not change parent responses, turns, prompt tracking, or timestamps.
- Child failures do not charge usage, still emit end status, and still close a
  constructed child.
- Permission inheritance remains in `SubagentFactory`; the executor does not
  infer or mutate permission state.
- Dynamic wakeup keeps clamping, pending state ownership, temporary registry
  scope, and cleanup semantics in `AutonomyRuntime`.

## Compatibility and rollback

There is no compatibility layer for removed Agent tool methods or the
controller field, per project policy. Tests and internal call sites are moved
to direct runtime/tool execution in the same change. Rollback is the single
Chinese commit for this scoped refactor; unrelated pre-existing `.claude`
changes are not staged.

## Verification design

Add focused architecture assertions for the removed field/protocol, forbidden
internal controller references, and capability/runtime source imports. Add or
update behavior tests for inline and fork Skill, unknown Skill, SubAgent
success/error/status/usage/close, Plan enter/exit/terminate, dynamic wakeup
temporary registration, permission inheritance, middleware execution, and
termination mapping. Run the repository's full quality matrix after focused
tests.
