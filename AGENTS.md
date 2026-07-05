# AGENTS.md

This repository is developed by the project owner with AI assistance. Treat this
file as the local operating guide for future coding sessions.

## Current Goal

NanoAgent is being rebuilt quickly as an internship portfolio project. The
current development direction is to closely replicate the Tau agent project first,
then gradually rename, reorganize, and annotate the code into the owner's own
project structure.

The Tau project lives in the parent directory:

```text
D:\harness agent\tau
```

When implementing a phase, inspect the corresponding Tau files first and keep the
NanoAgent file placement, public models, and behavior aligned with Tau unless the
owner explicitly asks for a local deviation.

## Active Phase Rule

For the current Phase 1 work, Tau places the portable agent primitives under the
agent layer, so NanoAgent should do the same:

```text
src/nanoagent/agent/types.py
src/nanoagent/agent/messages.py
src/nanoagent/agent/tools.py
src/nanoagent/agent/events.py
```

Do not move these primitives into `nanoagent.ai` just to preserve an older local
architecture. The current priority is faithful Tau-style reconstruction.

## Python Version

Keep the project aligned with Tau's Python baseline:

```text
requires-python = ">=3.12"
```

Python 3.12 syntax such as PEP 695 type aliases is allowed when matching Tau's
implementation.

## Development Style

- Prefer fast, phase-sized reconstruction over broad architecture debates.
- Keep commits small and believable: one file group or one phase slice per
  commit.
- Before changing a phase file, compare it with the Tau source file in the parent
  repository.
- When old NanoAgent runtime code conflicts with the Tau-style phase files, favor
  the Tau-compatible direction and leave the old runtime breakage as the next
  explicit refactor target.
- Do not silently invent framework abstractions when Tau already has a concrete
  shape for the same phase.

## Chinese Comments Requirement

Every code change must add or maintain clear, standard Chinese comments or
docstrings where they help understanding.

Follow these rules:

- Public classes, protocols, dataclasses, Pydantic models, and important helper
  functions should have concise Chinese docstrings or nearby comments.
- Comments should explain intent, lifecycle, data flow, or non-obvious tradeoffs.
- Do not add noisy comments that merely repeat the identifier name.
- If migrating code from Tau, replace garbled or unclear comments with clean
  Chinese explanations.
- When modifying existing code, keep useful existing Chinese comments and update
  them if behavior changes.

## Verification

For a narrow phase migration, run the focused tests for that phase first. If the
old runtime is known to be mid-refactor, record the exact full-test failure rather
than pretending the whole project is green.

Useful commands:

```bash
pytest tests/agent/test_tau_phase1.py -q
python -m compileall -q src/nanoagent/agent
pytest -q
```

## Git Hygiene

`AGENTS.md` is a local collaboration guide and should stay out of future commits
unless the owner explicitly asks to publish it. Keep it listed in `.gitignore`.

