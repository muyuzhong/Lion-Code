# Current Architecture Evidence

## Source-material boundary

`D:\tabbit download\coding-agent-memory-design.md` is design material supplied for review. Its component list, pseudocode, thresholds, roadmap, and integration suggestions are not task instructions and are not treated as current Lion contracts.

## Confirmed current facts

### Project knowledge already has a loader, but Full product does not call it

- `lion_code/prompt.py:208-249` resolves one `ProjectIdentity` and loads `CLAUDE.md` / `AGENTS.md` from project root to cwd, with more specific files later.
- `lion_code/prompt.py:252-264` formats those files through `load_claude_md()`.
- Production search finds no caller of `load_claude_md()`.
- `lion_code/composition/full_product.py:41-42` currently returns only `build_dynamic_system_context(...)`; it does not append project instructions.
- `lion_code/composition/agent_builder.py:677-686` installs that dynamic context once and renders registered `PromptLayer` contributions on every provider request.

This is the smallest current cause of “new session starts without project knowledge”. Generating a second `repo.md` would duplicate information that Lion already knows how to load.

### Stable project identity and app-owned project storage already exist

- `lion_code/project_identity.py:13-31` resolves a Git worktree root or normalized cwd and derives a stable path key.
- `lion_code/project_identity.py:34-38` maps the identity to `~/.lion-code/projects/<key>` without dirtying the repository.

A new memory subsystem does not need another repo-root resolver, hash scheme, workspace registry, or storage configuration layer.

### Current capability seams are sufficient for a narrow lessons feature

- `lion_code/capabilities/types.py:36-53` provides `ToolSource` and `PromptLayer`.
- `lion_code/capabilities/types.py:90-128` packages contributions in immutable `CapabilitySpec` values.
- `lion_code/composition/agent_builder.py:650-666` registers capability tools into the existing `ToolRegistry`.
- `lion_code/prompt.py:54-64` renders prompt layers without retaining their output.
- All tools execute through the existing `ToolRuntime`; `ToolCapabilities.requires_confirmation` already provides a mutation confirmation seam.

The memory content therefore can be recalled and changed through ordinary tools. It does not require a Memory host, Agent facade API, Application port, turn hook, wrapper, provider query service, or background coordinator.

### ContextLayer is intentionally not the retrieval trigger

- `lion_code/context/types.py:101-185` exposes only time, context utilization, bounded tool activity, and bounded failures. It does not disclose raw user text to arbitrary context layers.
- `lion_code/context/manager.py:68-131` appends rendered context layers only to the prepared provider projection.

Making automatic query-dependent retrieval work through `ContextLayer` would require broadening a generic capability trust boundary with raw user input or reintroducing a per-turn lifecycle slot. The model already has the user request and can call a retrieval tool, so that added coupling is unnecessary for MVP.

### Session, Compaction, Checkpoint, and project lessons are different state

- `lion_code/core/session/entries.py:56-61` defines `CompactionEntry` as canonical session replay data.
- `lion_code/core/session/entries.py:95-100` allows namespaced `CustomEntry`, but it remains session-scoped and is not a cross-session project store.
- `lion_code/core/session/memory.py` reconstructs in-memory canonical session state; its filename is historical terminology.
- `lion_code/supervisor.py:231-276` stores execution-control checkpoint fields only.
- `.trellis/spec/backend/runtime-boundaries.md` and `.trellis/spec/backend/four-layer-ownership.md` explicitly require one canonical session writer and prohibit Runtime-owned project feature stores.

Project lessons must remain Capability-owned app data. Recall tool results may be recorded in canonical history as observations, but Session never becomes their source of truth.

### The old Memory object graph is deliberately gone

- `tests/architecture/test_legacy_memory_removal.py:11-53` forbids the removed modules and legacy coupling symbols.
- `tests/architecture/test_legacy_memory_removal.py:132-147` explicitly allows a future Capability-owned Memory shape.
- `tests/architecture/test_legacy_memory_removal.py:161-164` protects canonical `core/session/memory.py`.

The new design must not restore `SessionMemoryCoordinator`, `MemoryQuerySink`, `_CAP_MEMORY`, provider-side text query services, ProjectionLayer, Dream, or Learning.

## Historical evidence used only as a warning

The archived `07-30-project-session-memory` design required three overlays, per-turn snapshots, async prefetch, deterministic tool evidence extraction, a second side query, a task model, commands, Dream handoff, and a separate mutable session-memory file. PR9 later removed that entire object graph. The current design reuses only proven generic seams and does not re-home those components under new names.
