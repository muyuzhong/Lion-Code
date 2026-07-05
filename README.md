# NanoAgent

NanoAgent is a small Python agent framework for local development. For now it serves one workflow: helping the project owner and AI agents build a clean agent runtime without pulling harness policy into the framework core.

The project is not a product layer yet. It currently contains the framework kernel: model/provider abstractions, wire messages, streaming events, tool execution, the agent loop, and a stateful `Agent` wrapper.

The active roadmap now follows Hugging Face Tau's proven Pi-style Python coding-agent phase order: keep the reusable core small, then grow a harness/application layer for coding tools, print CLI, JSONL sessions, `CodingSession`, skills/prompts, renderers, TUI, provider config, context management, and extensions. See `docs/superpowers/specs/2026-06-24-architecture-refinement-and-roadmap.md`.

## Current Scope

Implemented:

- `nanoagent.ai`: provider-facing message model, stream events, stream accumulator, model abstraction, provider registry, mock provider, and OpenAI-compatible provider.
- `nanoagent.agent`: runtime events, run result, context assembly, tool protocol, tool execution, control hooks, `agent_loop`, and stateful `Agent`.
- `nanoagent.utils`: small shared helpers such as IDs and logging.
- Tests for the core `ai` and `agent` paths.
- Import-layer checks through `import-linter`.

Not implemented yet:

- Harness/application layer.
- CLI, TUI, or web UI.
- Product-specific tool sets.
- Permission and approval policy beyond the runtime hook.
- Token budget policy.
- Mature provider behavior for production use.

## Directory Map

```text
src/nanoagent/
  utils/      # Base helpers with no framework-specific dependencies.
  ai/         # Model/provider layer, wire messages, stream events.
  agent/      # Runtime loop, tools, context, control, stateful Agent.

future harness/app packages may include:
  cli/              # Print mode first, TUI later.
  coding_agent/     # CodingSession, commands, provider setup, session orchestration.
  workspace/        # Concrete read/search/edit/bash/git tools.
  memory/           # Compaction, summaries, durable session/project memory.

tests/
  utils/
  ai/
  agent/

docs/
  superpowers/
    specs/    # Design notes from the planning process.
    plans/    # Implementation plans and task breakdowns.
    archive/  # Historical plans/specs that should not drive current work.
```

## Architecture

The dependency direction is:

```text
agent -> ai -> utils
```

`utils` stays generic. It must not know about models, messages, tools, or runtime policy.

`ai` owns model-facing concepts: wire messages, content blocks, provider abstractions, streaming events, stream accumulation, and provider adapters. Provider-specific code belongs under `nanoagent.ai.providers`.

`agent` owns runtime mechanics: context assembly, message conversion, tool execution, control hooks, multi-turn looping, terminal results, and the stateful `Agent` wrapper.

Anything that chooses a concrete provider, API key, tool policy, permission rule, budget, UI, or session lifecycle belongs in a future harness/application layer.

Roadmap order follows Tau; code boundaries follow NanoAgent. Concrete app capabilities should be added above `agent`, not smuggled into the core packages.

## Development Commands

Run the full test suite:

```bash
pytest -q
```

Run the import-layer contract:

```bash
pytest tests/test_import_contract.py -q
```

Install for local development:

```bash
pip install -e ".[dev]"
```

## Development Notes

Read `CLAUDE.md` before changing code with an AI agent. That file contains the project-specific constraints that should guide future edits.

The current codebase favors small files and explicit extension points. Do not split directories only for appearance; split when a module grows past one clear responsibility.
