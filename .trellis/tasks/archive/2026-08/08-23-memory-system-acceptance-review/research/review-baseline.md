# Review Baseline Evidence

## Source hierarchy

1. Latest user-approved convergence artifacts: commit `6c9fddd` on `muyuzhong/memory-design-convergence`.
2. Current implementation: `master` at review start; planning-time HEAD was `e01be42`.
3. Shipped implementation records:
   - `ee10c13` / PR #89 — Full project instructions;
   - `d6be834` / PR #90 — Session handoff;
   - `5a4b318` / PR #92 — SQLite/FTS5 semantic memory;
   - `ddb0c20` / PR #93 — query-aware automatic recall;
   - `dc73120` / PR #94 — archived parent and children.
4. Current backend specs and architecture tests.

## Planning-time divergence hypotheses

These are review targets, not findings until verified against current source and behavior:

| Latest convergence (`6c9fddd`) | Shipped task records on master |
| --- | --- |
| Project Task Ledger with on-demand continuation | Explicit Session handoff; no Task store claimed |
| AGENTS loading is outside Memory scope | PR1 changes Full project-instruction loading |
| Phase 1 has no production FTS or relevant auto-recall | PR3 ships FTS5; PR4 ships automatic relevant recall |
| Persisted active/archived only; dynamic needs-review | Persisted active/stale/archived plus revision chain |
| Typed single evidence (`user_request/source/test/command`) | Non-empty string-list evidence |
| Non-pinned writes may proceed; pin/unpin/purge require confirmation | PR3 states every mutation requires confirmation |
| Ordinary ContextLayer is sufficient for pinned | PR4 adds QueryContextLayer SPI |
| Lexical behavior must be prototyped before phase 2 | No separate offline prototype delivery appears in the shipped task tree |

## Enduring architecture boundary

- Session/history and Semantic Memory are separate owners.
- Memory may be capability-owned, but the removed Memory/Dream/Learning graph must not return.
- Prepared context is transient and must not become canonical Session history.
- Current user instructions, AGENTS, source and tests outrank recalled Memory.
