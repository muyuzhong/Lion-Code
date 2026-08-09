# State Ownership 分阶段迁移设计

## Target Ownership Map

| State | Target owner | Read boundary | Mutation boundary |
|---|---|---|---|
| Session identity | SessionIdentityState + SessionLifecycle | SessionView | SessionLifecycle new/restore |
| Permission | PermissionState + PermissionController | PermissionView | PermissionController commands |
| Plan | PlanState + PlanRuntime | PlanView | PlanRuntime enter/exit/toggle |
| Execution / cancellation | ExecutionControl + shared CancellationToken | CancellationView | ExecutionControl begin/cancel |
| Usage / budget | UsageLedger | UsageSnapshot | UsageLedger record operations |
| Provider configuration | existing AgentLifecycle, later ProviderManager | existing host boundary | deferred |
| Tool freshness | later ToolExecutionState/ReadFreshnessTracker | tracker query | deferred |

Memory ownership remains in `SessionMemoryCoordinator` / `MemoryCoordinator`; active tool ownership remains in `ToolRegistry`.

## Delivery Boundary

The parent task owns the source requirements, ordering, invariants and final integration review. It does not own product-code implementation. Each child task is one independently verifiable responsibility migration and must be safe to revert without reverting later unrelated work.

## Cross-Slice Rules

- State objects never appear twice as mutable values. Composition roots may pass references but may not mirror their fields.
- Read consumers receive a view or immutable snapshot. Mutable state classes remain private to their owner where practical.
- Commands own multi-field transitions. Direct assignment is allowed only inside the owning state/controller implementation.
- Public `Agent` properties may remain as read-only facade views when the CLI/TUI API requires them.
- A child may delete obsolete fields immediately; no compatibility adapter is allowed.
- Architecture tests should encode high-value ownership invariants instead of relying only on prose.

## Ordering Rationale

1. Session and cancellation are small, observable lifecycles and validate the ownership pattern with low product risk.
2. Permission depends on the read-view/write-controller split proven by the first slice.
3. Plan depends on PermissionController and moves a multi-field transaction only after permission ownership is stable.
4. Usage removes the largest remaining mirrored counter set after the control-path migrations are complete.

## Rollback

Each child has its own commit/PR boundary. Roll back only the failing child. No migration data or compatibility state is introduced, so rollback is a source-level revert plus its matching tests/spec change.
