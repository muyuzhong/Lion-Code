# PI-Desktop UI source audit

Research date: 2026-08-24.

## Pinned source

- Repository: https://github.com/vastsa/PI-Desktop
- Commit: `e56a3ed179a728723bde050f941e896922d67590`
- Desktop package: `apps/desktop`
- Stack: Electron 43, electron-vite 4, React 19, TypeScript 5.9, Tailwind 4, Zustand 5, lucide-react, custom Rust Host and Node agent sidecar.

## Relevant source size

| Source | Lines | Coupling |
| --- | ---: | --- |
| `Sidebar.tsx` | 1585 | PI API, app-store, shared project/session types, updater |
| `ChatSurface.tsx` | 256 | app-store, pending permission/ask selectors |
| `ChatTranscript.tsx` | 2480 | app-store, PI messages, preview/work-panel helpers |
| `Composer.tsx` | 1606 | app-store, API, queued prompts, plan and command state |
| `PermissionCard.tsx` | 155 | app-store and PI tool presentation |
| `PlanApprovalBar.tsx` | 319 | app-store, plan mode and work-panel tabs |
| `ToolDetails.tsx` | 281 | app-store, preview target and PI tool presentation |
| `tokens.css` | 243 | mostly portable visual tokens |
| `chat-shell.css` | 462 | portable after selector renaming |
| `messages.css` | 2517 | selective port required |
| `composer.css` | 595 | selective port required |

## Conclusion

The visual system is a strong fit, but whole-component copying would import a second state/runtime architecture and increase change size. The lowest-risk port is to reuse PI's information architecture, token values, CSS patterns and small rendering fragments while keeping Lion's `WorkspaceShell`, assistant-ui primitives and `LionAssistantRuntimeAdapter` as the behavior seams.
