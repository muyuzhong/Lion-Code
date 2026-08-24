# Desktop Sidecar Contract

## 1. Scope / Trigger

This contract applies to the Electron host under `desktop/`, the top-level
`lion_code.sidecar` process entry, and their Main/Preload/Renderer boundary. It
is required whenever code changes workspace selection, local protocol loading,
IPC, ready records, process startup/shutdown, capability delivery, or packaged
sidecar layout.

The Python entry is an Interfaces composition root. `lion_code.server` remains
an API/event adapter and must not import `lion_code.composition`; the executable
entry imports both `server.app` and `composition.full_product` from above that
boundary.

## 2. Signatures

```text
python -m lion_code.sidecar --workspace <absolute-directory>
stdin:  "shutdown\n"                     # graceful stop command
stdout: one UTF-8 ready JSON line only

SidecarController.start(workspacePath, command, args) -> Promise<void>
SidecarController.stop(graceTimeoutMs=5000) -> Promise<void>
DesktopBridge.connectWorkspace(path) -> Promise<void>
DesktopBridge.getBackendEndpoint() -> Promise<BackendEndpoint | null>
```

Packaged Windows builds run `python scripts/build_desktop_sidecar.py`, which
uses `scripts/lion-sidecar.spec` to create
`desktop/sidecar/lion-sidecar/lion-sidecar.exe`. `electron-builder` copies the
contents of that onedir folder to `resources/sidecar/`. The FastAPI app is an
API-only adapter; it must not locate, mount, or fall back to a browser frontend.

## 3. Contracts

- Ready schema is exact and rejects extra fields:
  `{"type":"ready","version":1,"port":1..65535,"capability":"[A-Za-z0-9_-]{32,128}"}`.
- The sidecar binds `127.0.0.1` with port `0`; capability is absent from argv,
  URL, persistent settings, session storage, ordinary logs, and chat history.
- Main retains one child handle and serializes start/stop/workspace-switch and
  pre-spawn failure operations. A ready child receives `shutdown\n`; timeout
  fallback terminates that exact owned process. Windows spawns use
  `windowsHide=true` while retaining stdio pipes.
- `lion://app` accepts only protocol `lion:` and hostname `app`. Production
  paths resolve inside Renderer root. Development proxy responses remain on
  the configured dev-server origin before being returned under the trusted
  scheme.
- IPC requires both the current `webContents.id` and an exact trusted frame URL.
  Preload exposes the typed `DesktopBridge` only, never raw IPC or Node APIs.
- `LION_SIDECAR_STATE_HOME` optionally isolates sidecar-owned configuration and
  session state inside the child process; Electron itself must not receive a
  substituted `HOME`/`USERPROFILE`.

## 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| empty, relative, missing, or non-directory workspace | `failed / workspace_invalid`; no spawn |
| packaged onedir executable missing | `failed / sidecar_assets_missing`; no fallback |
| spawn throws or emits `error` | `failed / spawn_failed` |
| first non-empty stdout record has wrong schema | `failed / invalid_ready`; child terminated |
| a second valid ready record appears | `failed / duplicate_ready`; child terminated |
| ready timeout expires | `failed / ready_timeout`; child terminated |
| ready child exits unexpectedly | `exited / sidecar_exited`; endpoint cleared |
| IPC sender ID or frame origin differs | invocation rejected |
| protocol host/path or development origin escapes | HTTP 404; no filesystem/network escape |

stderr retention keeps at least one maximum capability length before applying
redaction and the final diagnostic-tail truncation. Truncating first is
forbidden because a split token suffix would no longer match exact redaction.

## 5. Good / Base / Bad Cases

- Good: two workspace connections arrive concurrently; operations serialize,
  the previous child exits, and Main owns exactly the last child.
- Base: one absolute workspace starts, emits one ready record, and Renderer gets
  an in-memory loopback endpoint through checked IPC.
- Bad: `lion://app//evil.example/x` becomes a remote development fetch, an empty
  IPC path resolves to Electron cwd, or a second start overwrites a live child.

## 6. Tests Required

- Vitest: exact/extra ready schema, URL traversal and dev-origin confinement,
  exact navigation and sender identity, workspace absolute-path validation,
  preload allowlist, concurrent switching, duplicate ready, bounded stop, and
  redaction across the tail boundary.
- Python: API-only app, loopback dynamic port, stdout-only ready, capability not
  in argv, stdin shutdown, and clean real-process exit.
- Playwright: secure `lion://app` bootstrap, absence of Renderer Node/raw IPC,
  fake-sidecar switch/reap behavior, no session storage credential, and an
  explicit real Python sidecar project.
- Packaging smoke: build PyInstaller onedir, start its executable, parse ready,
  probe an authenticated REST route, send shutdown, and build wheel from the
  freshly produced sdist so stale build directories cannot hide Web assets.
- Electron package verification: reject Python source, old Web assets, and known
  development dependencies from both `resources/sidecar` and `app.asar`.
- Packaged Playwright: clear source-side Python discovery, force an invalid
  `LION_PYTHON`, connect a workspace through the bundled executable, then prove
  the owned sidecar is gone after Electron exits.
- Architecture: runtime-boundary AST/import-linter tests must treat top-level
  `sidecar` as an Interfaces module and keep Server away from Composition.

## 7. Wrong vs Correct

Wrong:

```typescript
const target = new URL(new URL(request.url).pathname, devServerUrl);
this.child = spawn(command, args); // concurrent starts can orphan the old child
```

Correct:

```typescript
const target = resolveDevProxyUrl(rendererRoot, request.url, devServerUrl);
return this.enqueue(() => this.startOwned(workspacePath, command, args));
```

The first form treats a trusted custom-scheme request as an unchecked network
URL and replaces process ownership concurrently. The second validates both
boundaries before crossing them.
