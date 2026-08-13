# Narrow Domain Runtime Agent Dependencies

## Goal

Refactor the Domain Runtime composition on the latest `master` after the
ProviderManager ownership migration so that Autonomy, Learning, Session Memory,
Dream, and, when it remains a small adjacent change, Subagent construction no
longer receive the whole `Agent` object. Each domain must receive only the stable
data, views, commands, and factories it actually consumes.

The change must preserve all current behavior and Dream security guarantees. It
must not begin the later PromptComposer, SessionParticipant, or AgentBuilder
stages.

## Confirmed Baseline

- The current branch is `master` at `5324b4a`; ProviderManager ownership was
  completed by `28d8bc5` and its Trellis task is archived.
- `AutonomyRuntime(self)`, `LearningRuntime(self)`,
  `SessionMemoryCoordinator(self, ...)`, `DreamCoordinator(agent)`, and
  `SubagentFactory(self)` still receive Agent-shaped hosts.
- `AutonomyHost`, `LearningRuntimeHost`, and `SessionMemoryHost` expose private
  runtime state and/or `Any`-typed tool objects. Dream directly reads Agent
  public and private attributes and owns the concrete restricted child subclass.
- `tests/test_dream.py` has a pre-existing uncommitted assertion that Dream
  refresh preserves deferred Capability tool metadata. This change must be
  preserved and integrated, not reverted.
- The focused baseline is green: 91 passed, 5 skipped, 5 subtests passed across
  autonomy, learning, session memory, Dream, capability migration, and runtime
  architecture tests.
- The worktree contains extensive unrelated Trellis/template changes. Only files
  owned by this task may be staged or committed.

## Requirements

### R1. Shared narrow runtime ports

- Establish low-level structural contracts for:
  - `TranscriptView.messages -> tuple[AgentMessage, ...]`
  - `NoticeSink.emit(message, role=...)`
  - `ConversationRunner.chat(prompt)`
  - `ModelQuery.complete_text(...)` and `ModelQuery.complete_messages(...)`
- Keep these contracts minimal and independent of `Agent`, Core Runtime
  implementation types, Provider implementations, tool objects, and UI types.
- A concrete Provider-backed query adapter may enforce API-configuration
  preconditions internally, but availability must not expand the `ModelQuery`
  protocol.
- Do not introduce `RuntimeContext`, `AgentServices`, `DomainContext`, or an
  equivalent service locator under another name.

### R2. Autonomy Runtime

- Delete `AutonomyHost`.
- Construct `AutonomyRuntime` from explicit conversation, transcript, model
  query, notice, cancellation, concrete `ToolRegistry`, confirmation, shared
  `UsageLedger`, and `BudgetPolicy` dependencies.
- Remove every import/reference to `Agent`, `_core_runtime`, and Core Runtime
  implementation details from `autonomy_runtime.py`.
- Preserve `/goal`, fixed and dynamic `/loop`, wakeup-tool lifetime, budget
  checks, cancellation, two-stage Auto Mode classification, read-only fast path,
  denial accounting, and fail-closed/manual-confirm fallback behavior.

### R3. Learning Runtime

- Delete `LearningRuntimeHost`.
- Construct `LearningRuntime` from `TranscriptView`, `ModelQuery`, and an
  immutable working-directory `Path`.
- Remove every import/reference to `Agent`, `_core_runtime`, and Core Runtime
  implementation details from `learning_runtime.py`.
- Preserve the one-query Meta-Skill decision, validation, rejection, scope, and
  no-overwrite behavior.

### R4. Session Memory Coordinator

- Delete `SessionMemoryHost` and the `_host` field.
- Inject explicit stable dependencies: `ProjectIdentity`,
  `SessionMemoryRepository`, `TranscriptView`, `CancellationView`,
  `PermissionView`, typed project-context loading, `NoticeSink`, the current
  Memory text-query service, `DreamRunner`, immutable `is_sub_agent`, and the
  narrow status/refresh callbacks actually used by Dream.
- Type project context and `MemoryCoordinator` state with concrete stable types;
  remove `Any` from the migrated boundary.
- Session Memory must not know `Agent`, `ToolContext`, `ToolEnvironment`,
  `ToolRegistry`, child configuration, Provider implementations, or Core Runtime
  implementations.
- Preserve project/session/auto overlay construction, deterministic tool
  evidence, semantic extraction, cancellation behavior, corrupt-file handling,
  task/handoff commands, Dream status, and post-Dream invalidation/refresh.

### R5. Dream domain and restricted child adapter

- Remove the `Agent` import, `agent` constructor argument, `self.agent` field,
  and all Agent private-field reads from `dream.py`.
- Define narrow `DreamAgentRunner` and `DreamAgentFactory` contracts with typed
  run output and explicit close behavior.
- Construct `DreamCoordinator` from `SessionRepository`, `ProjectIdentity`, a
  read-only Session Memory snapshot/view, `DreamAgentFactory`, and a narrow child
  usage recorder.
- Move the concrete restricted child subclass/factory to the Agent composition or
  adapter layer. Dream domain code may retain pure read-root validation policy,
  declarative plan validation, and atomic application logic.
- Preserve every security invariant:
  - only read-only `read_file`, `list_files`, and `grep_search` tools;
  - reads restricted to resolved project and Memory roots, with traversal denied;
  - MCP disabled;
  - no nested agent tool;
  - no shell or write tools;
  - `DREAM_MAX_TURNS` enforced;
  - untrusted inputs framed as data;
  - the entire declarative plan validated before mutation;
  - snapshot conflict detection and atomic apply/rollback preserved.

### R6. Subagent Factory

- If the change remains local to construction and inheritance tests, delete
  `SubagentFactoryHost` and construct `SubagentFactory` from concrete
  `ToolRegistry`, concrete `ToolEnvironment`, a typed child-config provider, and
  `PermissionView`.
- Keep it a child constructor, not a DI container.
- Preserve tool selection and `plan`/`auto` permission inheritance; other modes
  continue to produce `bypassPermissions` children.

### R7. Architecture enforcement and reporting

- Add AST/import architecture tests for the requested dependency boundaries and
  forbidden service-locator patterns.
- Domain constructors in this scope must not accept `agent` or `host` parameters.
- Key migrated protocols must not contain `tool_context: Any`,
  `tool_environment: Any`, `tool_registry: Any`, or `_core_runtime: Any`.
- The final report must state the old Agent-shaped dependencies, their new narrow
  replacements, the measured removal count for `Any` and private-runtime
  references, how every Dream security boundary remains enforced, and the full
  quality-gate result.

## Acceptance Criteria

- [ ] `autonomy_runtime.py` contains no import/reference to `Agent`,
  `_core_runtime`, or a Core Runtime implementation and receives only explicit
  narrow dependencies. [R1, R2]
- [ ] `learning_runtime.py` contains no import/reference to `Agent`,
  `_core_runtime`, or a Core Runtime implementation and receives transcript,
  query, and cwd explicitly. [R1, R3]
- [ ] `SessionMemoryHost` is removed; `SessionMemoryCoordinator` has no Agent,
  tool-object, child-config, Provider-implementation, or Core Runtime dependency.
  [R4]
- [ ] `dream.py` does not import `Agent`, and `DreamCoordinator` neither accepts
  nor stores an Agent-shaped object. [R5]
- [ ] Dream factory/runner boundaries are typed, and security tests prove
  read-only tools, restricted roots, no MCP/nesting/shell/write, max turns,
  declarative validation, conflict rejection, and rollback. [R5]
- [ ] `SubagentFactoryHost` is removed without broadening `SubagentFactory`, and
  permission/tool/environment inheritance remains covered. [R6]
- [ ] No new `*Context`/`*Services` service locator is introduced, and targeted
  constructors have no `agent`/`host` parameter. [R1, R7]
- [ ] Goal, loop, Auto classifier, learning, Session Memory read/update,
  semantic extraction, Dream success/error/rollback/security, and Subagent
  inheritance tests pass. [R2-R7]
- [ ] Full repository quality gates pass or any unrelated pre-existing baseline
  failure is isolated with evidence: full pytest, compileall, repository baseline
  checks, import-linter, focused static checks, task validation, and diff checks.
  [R7]
- [ ] Only task-owned files are committed, using a Chinese commit description;
  unrelated worktree changes remain untouched. [R7]

## Out of Scope

- PromptComposer extraction or redesign.
- SessionParticipant migration.
- AgentBuilder or a general-purpose DI container.
- New user-visible features, Provider behavior, persistence formats, migrations,
  compatibility adapters, or fallback paths.
- Any architecture stage after this Domain Runtime dependency narrowing.
