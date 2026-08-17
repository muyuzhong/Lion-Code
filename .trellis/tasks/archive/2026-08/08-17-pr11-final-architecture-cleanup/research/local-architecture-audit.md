# Local architecture audit before PR11

## Baseline

- Source of truth: local branch at `e966dc6` plus PR10 archive/session commits.
- PR10 focused tests: 87 passed.
- Architecture tests: 88 passed.
- Import-linter: 7 contracts kept, 0 broken.
- Full pytest: 707 passed, 3 skipped, 10 subtests passed; the known Windows GBK
  spinner thread warning remains baseline noise.

## Confirmed PR9/PR10 prerequisites

- Removed modules: root project Memory, session-memory coordinator/repository,
  `memory_runtime/`, Dream adapter/runtime and Learning runtime are absent.
- `MetaAgent` has no Memory/Dream/Learning/goal/autonomy/Plan/Skill/SubAgent API.
- ProjectionLayer and the per-request capability projection slot are absent.
- `supervisor.py` contains structural AgentPort/AgentFactory, execution-control
  checkpoint state, retry/scheduler and long-running orchestration only.
- Agent/Profile/Composition contain no Supervisor reference.

## Deviations to close

1. CodingProfile still has optional SkillComposition and conditionally builds
   Skill/SubAgent.
2. ProductFacadeKind and composition facade fields preserve a dual facade choice;
   FullProfile has no public Profile -> MetaAgent builder.
3. MetaAgent retains an unused private registry and Agent duplicates its common
   facade methods.
4. No single-omission Test C exists for ordinary CapabilitySpec peers.
5. Legacy guard globally forbids generic future-capability names.
6. Composition and MetaAgent dependency directions are documented but absent
   from import-linter.
7. Directory scan found no empty production directories; no broad move is needed.
8. Session JSONL save/replay/restore/compaction is one path and already tested;
   keep it unchanged.

## CodeGraph call-path evidence

```text
Profile -> _normalize_profile -> _build_capability_graph
        -> CapabilityRegistry/Runtime -> Tool/Prompt/Session slots
        -> AgentRuntimeCoordinator -> MetaAgent or internal Agent

Supervisor -> injected AgentFactory -> public AgentPort
           -> run/subscribe/restore/session_id/close only
```

Minimal resolves no built-ins. Coding currently resolves Skill/SubAgent only
when SkillComposition exists. Full always resolves Skill/SubAgent/Plan and then
registers extension_specs. This makes removal of Coding SkillComposition and
facade selection local to Profile/composition without touching Kernel or session
state owners.
