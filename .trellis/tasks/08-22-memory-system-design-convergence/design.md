# Lion Project Memory — Converged Technical Design

## 1. Decision

Do not implement the supplied four-store memory platform. Lion needs two deliberately different planes:

1. **Project Knowledge** — authoritative, versioned instructions and procedures already expressed by `AGENTS.md`, `CLAUDE.md`, `.trellis/spec/`, and Skills. The missing product wiring is to load the existing project instruction files in Full product.
2. **Project Lessons** — a small, local, non-authoritative set of evidence-backed cross-session lessons. It is a cohesive Capability with explicit recall/write/forget tools and one app-owned JSON snapshot.

There is no third “Session Memory” plane. Canonical Session, context compaction, Supervisor checkpoint, Plan state, Trellis tasks, and project lessons keep their existing or newly assigned single owners.

## 2. First-principles derivation

### Problem in one sentence

A fresh Lion session should obtain durable project rules and be able to reuse verified prior lessons without treating historical model output as current truth.

### Fundamental truths

| Truth | Consequence |
| --- | --- |
| Current source, tests, and project instructions are more authoritative than remembered text. | Memory is a hint with evidence, never an instruction or source of truth. |
| A fresh model request already contains the user's query and can call tools. | No task-start Hook or wrapper is required for query-dependent recall. |
| Automatic model-written durable state can poison every later session. | Writes are explicit tool calls, require evidence, and use the existing confirmation boundary. |
| Lion already resolves project identity and app-owned project storage. | Reuse `ProjectIdentity` and `project_storage_dir`; add no root/hash/config abstraction. |
| Repo rules and reusable procedures already have versioned homes. | Do not copy them into generated Repo/Procedure Memory. |
| The expected lesson corpus is small and local. | Deterministic in-memory scan is sufficient; no SQLite, FTS, embeddings, cache, or cron. |
| Session replay and Supervisor recovery solve different problems. | Do not persist lessons as Session entries or checkpoint fields. |

## 3. Review of the supplied design

| Proposed element | Verdict | Converged alternative |
| --- | --- | --- |
| Repo Memory / generated `repo.md` | Reuse existing ability; delete duplicate store | Load `AGENTS.md` / `CLAUDE.md`; route deeper rules to Trellis specs and Skills. |
| Coding Memory | Keep, but narrow | Store only reusable, evidence-backed project lessons. |
| Preference Memory | Remove from this feature | Caller/user configuration or system prompt owns collaboration preferences. |
| Procedure Memory | Remove from this feature | Skills and `.trellis/spec/` own executable procedures. |
| Unified four-type schema | Delete | One `ProjectLesson` schema; no unused `type`, `scope`, `status`, or usage counters. |
| Markdown + JSONL + SQLite triple storage | Delete | One strict, atomic `lessons.json` under app-owned project storage. |
| FTS5 / BM25 / weighted score | Defer | Small deterministic lexical scan with path/key matches and bounded top results. |
| Task-start Hook / Agent wrapper | Delete | PromptLayer tells the model to call the ordinary recall tool before redundant exploration. |
| Task-end background LLM extractor | Delete | The active model proposes one explicit `remember_project_lesson` call; no second model request. |
| Semantic dedupe thresholds (`0.85`, `0.9`) | Delete | Exact stable key updates one entry; different keys stay distinct until a human removes one. |
| Newer timestamp wins on conflict | Reject | Current code/evidence wins; conflicting memory is verified, then updated or forgotten explicitly. |
| `use_count` / `last_used_at` mutations | Delete | Recall is read-only; no hidden write on read. |
| Daily decay / weekly consolidation | Delete | Explicit forget and exact-key replacement; add maintenance only after measured corpus-quality failure. |
| Hidden `<memory>` prompt injection | Delete for dynamic lessons | Recall returns an ordinary tool result, visible and auditable in canonical Session. |
| CLI, Viewer, config weights, cron expressions | Defer | Model-facing tools are the MVP control plane. |

## 4. Target architecture

```text
FullProfile
  -> Project Instructions (existing loader, dynamic system context)
  -> ProjectLessons Capability
       -> ProjectLessonsPromptLayer (behavior only, no stored content)
       -> recall_project_lessons   [read-only]
       -> remember_project_lesson  [confirmation]
       -> forget_project_lesson    [confirmation]
       -> ProjectLessonRepository
            -> ~/.lion-code/projects/<project-key>/lessons.json

Tool calls -> existing ToolRuntime -> permission/audit middleware -> ToolResult
ToolResult -> ordinary canonical Session JSONL observation
```

### Ownership

| State | Single owner | Persistence / projection |
| --- | --- | --- |
| Project rules and procedures | Repository authors / project files | Versioned `AGENTS.md`, `CLAUDE.md`, `.trellis/spec/`, Skills; system prompt only |
| Project lessons | `ProjectLessonRepository` inside `capabilities/project_lessons/` | App-owned `lessons.json`; recalled through tools |
| Conversation and recalled observations | `SessionRuntime` / `SessionRecorder` | Existing append-only Session JSONL |
| Context pressure and summaries | `ContextRuntime` / existing compactor | Existing validated `CompactionEntry` path |
| Long-running execution recovery | `Supervisor` | Existing checkpoint schema; no lesson content |
| Plan task state | `PlanRuntime` / Trellis task artifacts | Existing Plan/Trellis contracts; no lesson mirror |

Neither Agent Runtime nor `MetaAgent` gains a memory field, repository reference, command delegate, or query port. `AgentComposition` does not expose the repository as a service locator.

## 5. Project Knowledge path

The existing `load_project_context_files()` behavior is retained: resolve one project identity, load root-to-cwd `CLAUDE.md` then `AGENTS.md`, and keep the more specific content later.

`build_full_coding_backend()` changes only its existing dynamic-context builder so the default Full product combines:

```text
Environment / Git / deferred-tool context
+ existing load_claude_md() result
```

No generated Repo Memory file, repo scan, Git commit watcher, or write-back exists. A caller-supplied custom system prompt keeps its current opt-out semantics unless a separate product decision changes that contract.

## 6. Project Lessons capability

### Package shape

Use the fewest cohesive files:

```text
lion_code/capabilities/project_lessons/
├── __init__.py
├── capability.py     # CapabilitySpec, PromptLayer, three LionTools
└── repository.py     # strict model, load/search/upsert/delete, atomic persistence
```

Do not introduce `MemoryRuntime`, `MemoryCoordinator`, `MemoryHost`, `MemoryQuerySink`, a repository Protocol with one implementation, or a background resource.

### Stored contract

```json
{
  "project_root": "D:/harness agent/Lion",
  "lessons": [
    {
      "key": "context-runtime-plan-independence",
      "content": "ContextRuntime must resolve objectives without PlanRuntime coupling.",
      "evidence": ["tests/architecture/test_runtime_ownership.py", "commit 59e18a5"],
      "paths": ["lion_code/runtime/context.py"]
    }
  ]
}
```

Only these fields exist in MVP:

- `key`: stable human-readable identity used for exact replacement;
- `content`: concise reusable claim, constraint, failed approach, or regression check;
- `evidence`: at least one current source/test/command/commit/user-decision reference;
- `paths`: optional normalized project-relative hints.

There is no `version`, `type`, `scope`, `status`, timestamp, usage counter, archived copy, superseded chain, or semantic vector. A changed schema is an intentional breaking design change, not a migration branch.

### Persistence

- Resolve `ProjectIdentity` once from the composition cwd.
- Store at `project_storage_dir(identity) / "lessons.json"`; never dirty the repository.
- Strictly validate `project_root`, field types, entry bounds, and unique keys.
- Load the whole file because the corpus is small.
- Upsert/delete by rewriting a temporary file, flushing/fsyncing it, then `os.replace`, following the existing Supervisor checkpoint pattern.
- Missing file means an empty set. Invalid UTF-8, malformed JSON, wrong root, duplicate keys, or unknown fields raise a clear repository error and are never overwritten by an empty state.
- `forget_project_lesson` physically removes the entry; it does not pretend that archived data was forgotten.
- Forgetting does not rewrite append-only Session JSONL that already recorded an earlier recall result; deleting historical sessions is a separate user-authorized operation.
- No migration or fallback is provided. A future schema change replaces the contract through a separately reviewed design.

### Retrieval

`recall_project_lessons(query, paths=())` is a read-only tool. It scans current entries and ranks them deterministically:

1. exact key or exact path match;
2. number of distinct case-folded query terms found in key/content/paths;
3. `key` ascending for a stable final tie-break.

Return at most five entries and cap the combined output at a fixed 2,000 characters. Include each entry's key, content, evidence, and relevant paths plus an omission marker when cropped. Empty query lists keys only; zero matches is a normal empty result.

There are no configurable weights, recency decay, use-count feedback loop, semantic calls, or implicit stale checks. The PromptLayer states: memories are historical evidence, current source wins, verify before acting, and call recall before repeating broad exploration in a fresh project task.

### Write and forget

- `remember_project_lesson` requires a stable key, concise content, at least one evidence item, and optional repo-relative paths.
- A new key adds one entry; the same key replaces it atomically. It never searches for semantic neighbors.
- `remember_project_lesson` and `forget_project_lesson` use `ToolCapabilities.requires_confirmation=True`; `recall_project_lessons` is read-only and concurrency-safe.
- They follow the existing permission modes exactly: `bypassPermissions` remains an intentional bypass rather than gaining a feature-specific hard gate.
- The main model may propose a write after a verified task; there is no background LLM call or task-end hook.
- One-time progress, active goals, pending steps, raw conversation summaries, secrets, transient failures, and unverified guesses are rejected by prompt contract and tool validation where mechanically possible.

All three operations use the sole `ToolRuntime.execute` route, so current permission, secret, audit, error, and result semantics remain in force.

## 7. Composition boundary

`FullProfile` selects a built-in `project_lessons` Capability beside Plan, Skill, and SubAgent. Composition constructs it from the existing cwd/project identity and registers its immutable `CapabilitySpec`.

Use a new `_CAP_PROJECT_LESSONS` selection name if the current builder needs a branch. Do not revive the forbidden legacy `_CAP_MEMORY` symbol. CodingProfile and MinimalProfile remain unchanged; callers can still supply an explicitly constructed spec through `extension_specs` if they want the feature there.

The capability contributes tools and a PromptLayer only. It does not contribute a `ContextLayer` or `SessionParticipant`, and no Runtime module changes.

## 8. Error and safety matrix

| Condition | Required result |
| --- | --- |
| No lessons file | Recall returns empty; no file is created. |
| Malformed/corrupt file | Clear tool error; remember/forget refuse to overwrite. |
| Store belongs to another normalized root | Clear identity error; no fallback or cross-project read. |
| Recall has no match | Empty result; agent continues with current-source exploration. |
| Result exceeds budget | Deterministic truncation with omission marker. |
| Duplicate remember key | Exact atomic replacement. |
| Conflicting different key | Both remain visible; agent verifies source and explicitly forgets/updates. |
| User rejects mutation confirmation | No file change; ordinary permission-denied result. |
| Memory conflicts with current code | Current code wins; memory is updated or physically forgotten. |
| Session is restored | Historical recall result remains in transcript; future recall reads the current lesson store. |

## 9. Deliberately deferred additions

Add complexity only after evidence proves the current mechanism fails:

- **SQLite FTS5**: only if measured corpus size/search latency or lexical miss rate makes an in-memory scan inadequate.
- **Automatic extraction**: only if users consistently miss valuable lessons and a reviewed evaluation shows acceptable contamination rate.
- **Automatic stale detection**: only if stale-memory incidents persist despite evidence display and current-source verification.
- **Consolidation/decay jobs**: only if duplicate/noise growth is measured; prefer a one-shot explicit maintenance command before a scheduler.
- **CLI/TUI viewer**: only if model-facing list/search/forget is insufficient for real management workflows.
- **Semantic/vector retrieval, global preference store, multi-agent sharing, cloud sync**: separate product decisions, not MVP extensions.

## 10. Rollback and compatibility

- No legacy Memory data or API is migrated; none exists in the current product contract.
- Project Knowledge wiring can be reverted independently without touching Session or lessons data.
- Project Lessons can be removed by unregistering the Capability; the local `lessons.json` remains a recoverable user file and no Runtime schema changes are required.
- Session JSONL, `CompactionEntry`, Supervisor checkpoints, Plan state, and existing ContextLayer behavior remain byte-for-byte compatible because this design does not edit their schemas or ownership.
