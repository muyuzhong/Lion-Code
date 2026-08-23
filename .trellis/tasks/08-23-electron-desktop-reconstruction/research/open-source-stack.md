# Open-source desktop stack research

Research date: 2026-08-23.

## Selected stack

| Concern | Selection | License | Reason |
| --- | --- | --- | --- |
| Electron build | `electron-vite` | MIT | Builds Main/Preload/Renderer with Vite; actively used by current OpenCode Desktop. |
| Packaging | `electron-builder` | MIT | Windows installer and resource packaging; `extraResources` is designed for native sidecars. |
| Chat runtime | `assistant-ui` | MIT | Composable Thread/Composer/Message/Tool primitives plus custom/external-store runtime support. |
| Streaming Markdown | `Streamdown` | Apache-2.0 | Handles incomplete streaming Markdown, Shiki code, GFM and optional CJK/diagram/math plugins. |
| UI primitives | Radix + selected shadcn/ui source | MIT | Accessible low-level behavior while retaining full Lion visual ownership. |
| Sidecar freeze | PyInstaller `onedir` | GPL-2.0-or-later WITH Bootloader-exception | Produces a Windows standalone folder and avoids `onefile` startup extraction. |

## Reference products

- OpenCode Desktop (`anomalyco/opencode`, MIT) currently has an Electron desktop package using `electron-vite` and `electron-builder`. Use as a process/package architecture reference, not as a UI dependency.
- Goose (`aaif-goose/goose`, Apache-2.0) is useful for agent-desktop behavior study but uses a different Rust/Tauri architecture.
- Cherry Studio (AGPL-3.0) and Chatbox (GPL-3.0) may be studied for interaction patterns only. Do not copy their code into Lion unless Lion deliberately adopts the corresponding copyleft license.
- Vercel AI Elements (Apache-2.0) is a source component catalog. It is not selected as a second chat runtime; individual visual ideas may be reimplemented against assistant-ui.

## Security findings

- Electron recommends context isolation, renderer sandboxing, disabled Node integration, restricted navigation and narrow IPC sender validation.
- Electron recommends a custom local protocol instead of `file://`; the protocol handler must restrict resolved paths to the packaged renderer root.
- The sidecar capability must not travel in a URL, command line or persistent browser storage. The parent-child ready pipe plus typed preload bootstrap is the selected delivery mechanism.

## Distribution findings

- electron-builder `extraResources` copies native binaries/resources outside ASAR into the installed resources directory, addressable through `process.resourcesPath`.
- PyInstaller supports both `onedir` and `onefile`; `onedir` is selected because a desktop sidecar is started repeatedly and should not unpack itself for each launch.
- Windows signing and auto-update are intentionally deferred from the MVP, but the packaging layout must not prevent adding them later.

## Sources

- https://github.com/anomalyco/opencode/tree/dev/packages/desktop
- https://github.com/alex8088/electron-vite
- https://github.com/electron-userland/electron-builder
- https://www.electron.build/docs/contents/
- https://www.electronjs.org/docs/latest/tutorial/security
- https://www.electronjs.org/docs/latest/api/protocol/
- https://github.com/assistant-ui/assistant-ui
- https://github.com/vercel/streamdown
- https://github.com/shadcn-ui/ui
- https://github.com/radix-ui/primitives
- https://pyinstaller.org/en/stable/usage.html
- https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt
