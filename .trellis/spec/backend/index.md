# Backend Development Guidelines

> Current Lion Code runtime development conventions. These files describe the
> repository as it exists today, rather than a generic web-service architecture.

---

## Overview

This directory contains guidelines for backend development. Fill in each file with your project's specific conventions.

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Runtime module organization and file layout | Active |
| [Database Guidelines](./database-guidelines.md) | Local JSONL persistence and legacy migration boundary | Active |
| [Memory Capability](./memory-capability.md) | Capability-owned Task Ledger and Semantic Memory SQLite contract | Active |
| [Error Handling](./error-handling.md) | Error types, handling strategies | Active |
| [TUI Interaction](./tui-interaction.md) | Input, completion, streaming, and frontend ownership contracts | Active |
| [Runtime Boundaries](./runtime-boundaries.md) | Core/Provider, session persistence, and frontend ownership contracts | Active |
| [Four-Layer Ownership](./four-layer-ownership.md) | Kernel/Harness/Capability/Supervisor layer ownership view (test ownership: `tests/OWNERSHIP.md`) | Active |
| [Usage Ownership](./usage-ownership.md) | Usage single-writer, budget, lifecycle, and projection contracts | Active |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, testing, and review checks | Active |
| [Logging Guidelines](./logging-guidelines.md) | Event-based observability and terminal presentation | Active |
| [Tool Runtime Workspace Recovery](./tool-runtime-recovery.md) | Snapshot, rollback result, and execution audit contracts | Active |
| [Secret Boundary](./secret-boundary.md) | Secret registration, fingerprint redaction, and sanitizer pipeline contracts | Active |
| [Egress Guard](./egress-guard.md) | Trust domain, Level A/B egress promises, whitelist growth contracts | Active |
| [Agent E2E Evaluation](./agent-e2e-evaluation.md) | Versioned evaluation contracts, isolation, and offline-only behavior | Active |

---

## How to Use These Guidelines

When updating a guideline file:

1. Document your project's **actual conventions** (not ideals)
2. Include **code examples** from your codebase
3. List **forbidden patterns** and why
4. Add **common mistakes** your team has made

The goal is to help AI assistants and new team members understand how YOUR project works.

---

**Language**: All documentation should be written in **English**.
(`four-layer-ownership.md` is the current exception — written in Chinese per the PR0
task requirement; its structure mirrors the English contract docs.)
