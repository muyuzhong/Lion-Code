# Desktop Chat Experience Contract

## 1. Scope / Trigger

This contract applies to the Electron Renderer shell, workspace/session navigation,
Provider settings, theme, approvals, and assistant-ui presentation under
`desktop/src/renderer`. Read it before changing desktop information architecture or
adding Renderer-owned state.

## 2. Signatures

```typescript
LionRestClient.fetchStatus(): Promise<ServerStatus>
LionRestClient.fetchSessions(): Promise<SessionSummary[]>
LionRestClient.fetchModels(): Promise<ModelChoice[]>
LionRestClient.fetchSkills(): Promise<SkillSummary[]>
LionRestClient.configureProvider(configuration: ProviderConfiguration): Promise<void>
LionRestClient.setThinkingLevel(level: string): Promise<void>
```

The Renderer may persist only presentation preferences such as `lion-theme`.
Session messages, Provider configuration, model, Thinking, and workspace eligibility
remain Python-owned and are refreshed from REST after writes.

## 3. Contracts

- `WorkspaceShell` owns sidebar collapse, theme, open panels, and composer draft seeds;
  `LionAssistantRuntimeAdapter` remains the only message/run projection owner.
- REST metadata uses the existing strict response fields. A malformed status, session,
  model, or Skill response is an explicit metadata error, never a permissive cast.
- Provider forms never populate or reveal the stored API key. An empty key preserves the
  current credential through the server's partial-update contract.
- `api_configured=false` opens the first-run Provider surface once. Closing it is allowed;
  it must not reopen on every snapshot.
- Approval dialogs focus the safe action. Escape maps to deny for Permission and
  `keep-planning` for Plan approval.
- Light and dark themes use the same semantic tokens. Status always has text or a label in
  addition to color, and `prefers-reduced-motion` disables spatial animation.

## 4. Validation & Error Matrix

| Condition | Renderer behavior |
| --- | --- |
| metadata response is non-2xx or invalid | keep chat transport usable and show a diagnostic metadata error |
| Provider/Thinking write fails | keep settings open and show the server detail |
| active run | disable Session, Provider, and Thinking mutations |
| `api_configured=false` | open first-run settings without exposing a credential value |
| 1280x720 or 2560x1440 | no document-level horizontal overflow; composer and approvals remain reachable |
| reduced motion | state remains legible with animations effectively disabled |

## 5. Good / Base / Bad Cases

- Good: a Provider save succeeds, metadata refreshes, and the user returns to the same
  assistant-ui Thread without creating a second chat store.
- Base: no prior sessions or Skills yields instructive empty copy and a usable composer.
- Bad: component `useState` duplicates messages, API credentials are inserted into form
  defaults, or Escape implicitly approves a blocking request.

## 6. Tests Required

- Vitest: strict metadata decoding, metadata actions, relative-time boundaries, and the
  existing protocol/runtime suite.
- Electron Playwright: REST history to streamed response, 1280x720 and 2560x1440 overflow
  checks, both themes, and screenshots for the desktop chat state.
- Run `npm test`, `npm run typecheck`, `npm run build`, and all Playwright projects with one
  worker when real sidecar projects share machine resources.

## 7. Wrong vs Correct

**Wrong:** load metadata and canonical history as one blocking `Promise.all` before opening
WebSocket. A slow optional endpoint makes an otherwise healthy chat appear unavailable.

**Correct:** await canonical history before connecting WebSocket, then refresh auxiliary
metadata independently and surface its failure separately.
