# Current Web Boundary Review

## Scope

Current on-disk FastAPI server, React client, Application port, CLI startup,
packaging configuration, and `tests/server/test_server_api.py` on 2026-08-22.

## Confirmed defects

1. `lion_code/server/app.py:43-49,221-225` accepts arbitrary REST Origin and
   WebSocket Origin with no process credential. A `https://evil.example`
   preflight returned 200 with that Origin and credentials enabled; its
   WebSocket handshake was accepted.
2. `lion_code/server/app.py:176-201` sends sparse persistence kwargs to the
   full-value `save_api_config` signature. Model-only and provider+model
   requests both returned 500 after one runtime configure call.
3. `lion_code/server/bridge.py:107-159` dispatches raw dictionaries instead of
   the declared action models. `approved: "false"` resolved a pending approval
   as `True`.
4. Core tool events serialize as `toolCallId`, `toolName`, and `isError`;
   `frontend/src/hooks/useLionChat.ts:105-149` reads snake-case identifiers and
   misses the error flag. `AgentToolResult` is a structured content envelope,
   not a display string.
5. WebSocket callbacks are instance-global on one `LionCodingSession`. Binding
   two bridges then closing the first leaves the second with no confirm
   callback. Disconnect also leaves the active bridge run without an explicit
   convergence path.
6. `frontend/src/components/chat/SettingsModal.tsx:14-38` initializes from a
   usually-null status and never refreshes its draft. The Plan button sends a
   normal prompt rather than the existing `command` action.
7. `lion_code/server/app.py:133-135` returns all workspaces when the filtered
   current-workspace list is empty.
8. `tests/server/test_server_api.py:132-152` calls the real config writer and
   overwrote `~/.lion-code/config.json` with test credentials.
9. Server shutdown never calls `LionCodingSession.aclose()`. Static assets are
   loaded from ignored source-tree `frontend/dist`, outside the Python wheel.

## Existing invariants to preserve

- `LionCodingSession` is the interface boundary; Server must not import Runtime,
  Composition, Tooling, Provider, or TUI implementations.
- Core/Application camelCase wire events are canonical. The Web client adapts
  to them; Core does not gain Web aliases.
- Canonical messages and JSONL remain the only durable transcript. Reconnect
  replaces provisional client state from `/api/messages`.
- Confirmation, Plan approval, and notice callbacks have one frontend owner.
- ProviderController remains the only live provider-state write owner.
- Tests must inject all filesystem and browser effects.

## Validation already run

- `python -m pytest tests/server/test_server_api.py -q` -> 8 passed, but exposed
  the real-config write defect.
- `python -m ruff check lion_code/server tests/server` -> passed.
- Frontend TypeScript no-emit check -> passed; it cannot detect the drift because
  WebSocket events and `Response.json()` are typed as `any`.

## Git baseline

`origin/master` is `46500c0`. The current local HEAD `094dedc` contains the Web
baseline plus unrelated unmerged Security Plane work; a tree comparison shows
161 changed files. PR #73 merged only two ContextView files. Preserve current
dirty tracked files and do not publish the whole local tree as one master PR.
