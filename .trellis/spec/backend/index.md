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
| [Error Handling](./error-handling.md) | Error types, handling strategies | Active |
| [TUI Interaction](./tui-interaction.md) | Input, completion, streaming, and frontend ownership contracts | Active |
| [Runtime Boundaries](./runtime-boundaries.md) | Core/Provider, session persistence, and frontend ownership contracts | Active |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, testing, and review checks | Active |
| [Logging Guidelines](./logging-guidelines.md) | Event-based observability and terminal presentation | Active |

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
