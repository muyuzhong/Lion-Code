# PR11 Final Architecture Cleanup — Design

## 1. Final object graph

```text
Interfaces (CLI / Application / TUI)
              |
              v
       Composition / Profile
              |
              v
          MetaAgent facade
          /       |       \
     Kernel    Harness   Capability Plane

Supervisor -- AgentFactory --> build_profile_agent(Profile) --> MetaAgent
```

`MetaAgent` is the only package-level Agent facade. The existing `Agent` class
remains an internal Full/Coding application backend because `LionCodingSession`
needs UI controls such as Plan approval, terminal callbacks and legacy session
listing. It subclasses/reuses `MetaAgent` for the generic surface instead of
duplicating it, and is not exported from `lion_code.__init__`.

## 2. Profile contract

Profiles remain frozen/slots values and no longer select a facade:

```text
MinimalProfile
  config + dependencies + caller tools + generic prompt/policy

CodingProfile
  config + dependencies + Coding backend/tools/policy/prompt

FullProfile
  Coding fields + fixed Skill/Plan/SubAgent + extension_specs
```

`ProductFacadeKind`, `SkillComposition`, `_ProfileSelection.facade`, and
`AgentComposition.facade` are deleted. Coding no longer creates Skill or hidden
child machinery. Full remains the only built-in path that constructs Plan,
Skill and SubAgent.

## 3. Facade construction

`build_profile_agent(profile)` calls the existing one-shot
`build_agent_composition(profile)` and projects only generic owners into a
`MetaAgent`. The facade stores runtime coordinator, provider manager, session
identity, usage, budget and permission view. It does not store the composition,
registry, Profile, Plan, Skill or SubAgent.

`build_meta_agent()` and `build_coding_agent()` only build their profile value
and delegate to `build_profile_agent()`. A Full caller can construct
`build_profile_agent(FullProfile(...))`; Supervisor factories use this public
path but Supervisor itself never imports Profile or MetaAgent.

The internal `Agent` application backend builds a FullProfile once, initializes
the shared MetaAgent base with generic owners, then retains only the additional
application/control owners required by `CodingSessionBackend`.

## 4. Capability incrementality

The Composition Root still creates the concrete runtimes required by a selected
Profile, then converts Plan, Skill, SubAgent and each external extension into
ordinary `CapabilitySpec` registrations. Kernel/Harness consumes only aggregate
tool/prompt/lifecycle/resource slots.

Test C constructs the four specs as peers and verifies all single-omission
subsets plus the empty subset. It exercises registry resolution and
`CapabilityRuntime` lifecycle. Separate real Profile smoke tests prove Minimal,
Coding and Full MetaAgent graphs run. No mutable unregister operation is added:
removal means composing a graph without that immutable spec.

## 5. Legacy guard shape

The guard separates three concepts:

1. permanently removed legacy module roots/directories;
2. exact old coordination/coupling symbols and `_CAP_MEMORY` outside any future
   capability implementation;
3. generic future capability naming, which is allowed.

The scanner accepts a path and AST. A self-test feeds synthetic
`capabilities/memory.py` source containing `MemoryCapability` and a
`CapabilitySpec`; it must produce no violation. Synthetic old
`session_memory_coordinator.py`, `_CAP_MEMORY`, provider text-query and project
Memory coordinator shapes must be rejected. The production scan still proves
the current repository contains none of them.

## 6. Dependency contracts

Two import-linter/AST contracts are added to the existing single source of truth:

- Composition may depend downward on Kernel/Harness/Capability owners but not on
  Interfaces, Supervisor, MetaAgent or Agent facade modules.
- MetaAgent may depend on Composition and generic runtime owners but not on
  Application/TUI/Supervisor/Agent or concrete Capability modules.

Existing Core, Supervisor, Providers, Application, TUI, Capabilities and
production-vs-tests contracts remain. This avoids a broad physical directory
move while making the current ownership map executable.

## 7. Persistence and rollback

SessionRepository/Recorder, SessionLifecycle and compaction entries are not
modified except for callers needed by facade deduplication. Existing focused
save/new/restore/compaction tests and full suite are the behavioral guard.

PR11 is one rollback point after PR10. Reverting it restores the dual facade and
optional Coding Skill shape without changing session files, Supervisor
checkpoints or external data.
