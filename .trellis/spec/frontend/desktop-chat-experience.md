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
LionRestClient.renameSession(sessionId: string, label: string): Promise<void>
LionRestClient.fetchModels(): Promise<ModelChoice[]>
LionRestClient.fetchSkills(): Promise<SkillSummary[]>
LionRestClient.fetchProviderConfiguration(): Promise<ProviderConfigurationResponse>
LionRestClient.configureProvider(configuration: ProviderConfiguration): Promise<void>
LionRestClient.setThinkingLevel(level: string): Promise<void>
```

`ProviderConfigurationResponse` is the explicit settings readback contract:

```typescript
type ProviderConfigurationResponse = {
  provider: "openai" | "anthropic";
  model: string;
  api_key: string;
  base_url: string;
};
```

The Renderer may persist only presentation preferences such as `lion-theme`,
`lion-sidebar-width`, and `lion-work-panel-width`.
Session messages, Provider configuration, model, Thinking, and workspace eligibility
remain Python-owned and are refreshed from REST after writes.

## 3. Contracts

- `WorkspaceShell` owns sidebar collapse, theme, open panels, and composer draft seeds;
  `LionAssistantRuntimeAdapter` remains the only message/run projection owner.
- Sidebar and work-panel resizing is presentation-only state. Both resize surfaces use an
  accessible vertical separator with pointer and Arrow-key input, clamp against the current
  viewport, and always reserve at least 360px for the chat pane. Persisted sizes may be
  restored on a different display but must be re-clamped before rendering.
- Visible core chrome is functional: session search filters the canonical REST session list,
  project disclosure only changes presentation, model/thinking controls open the existing
  Python-backed settings surface, and message copy uses assistant-ui `ActionBarPrimitive`.
  The work-panel switcher may own its empty-view selection locally, but it must not invent
  file/browser resource state before those backend capabilities exist.
- 会话标题属于 Python canonical Session 元数据。Renderer 通过
  `POST /api/sessions/rename` 提交 `{ session_id, label }`，成功后重新读取
  `/api/sessions`；标题以 append-only `LabelEntry` 保存，禁止只写 localStorage 或
  Renderer `useState`。空白标题返回 422，跨 workspace / 不存在会话返回 404，运行中返回 400。
- Composer 的 `/` 候选使用 assistant-ui `Unstable_TriggerPopover` 与
  `unstable_useSlashCommandAdapter` 消费 `/api/skills` 的 canonical 只读列表。
  选择候选后写入 `/<skill-name> `，最终发送仍由 `actionForInput` 转成 command action；
  Escape 关闭候选，Arrow / Enter 遵循 primitive 的键盘语义。
- Composer textarea 必须覆盖全局 `textarea:focus-visible` outline；聚焦时保留
  Composer 既有壳层边界和输入光标，不得额外出现 textarea 内层矩形框或改变整块
  Composer 阴影。
- REST metadata uses the existing strict response fields. A malformed status, session,
  model, or Skill response is an explicit metadata error, never a permissive cast.
- Provider settings are read from the Python-owned `GET /api/config/provider` snapshot
  when the surface opens. The response is capability-protected and is not folded into
  `/api/status`, history, ordinary logs, or error text. The API key is rendered as a
  password by default; an explicit eye action may reveal it for the current surface only.
- Provider writes await only the canonical Python-owned write. Auxiliary metadata refresh
  runs independently after a successful write, so a slow or unavailable metadata endpoint
  cannot leave the settings save pending; refresh failures still update `metadataError`.
- An empty submitted key preserves the current credential through the server's
  partial-update contract. This task does not change the existing on-disk credential
  persistence or add disk encryption.
- `api_configured=false` opens the first-run Provider surface once. Closing it is allowed;
  it must not reopen on every snapshot. Sending without a configured API must render a
  terminal assistant error and return the composer to an idle, usable state.
- Approval dialogs focus the safe action. Escape maps to deny for Permission and
  `keep-planning` for Plan approval.
- Light and dark themes use the same semantic tokens. Status always has text or a label in
  addition to color, and `prefers-reduced-motion` disables spatial animation.
- 移植外部桌面 UI 时只复用视觉结构、语义 token 与纯展示片段。展示组件只接收数据和
  callback；`WorkspaceShell` / `ChatThread` 仍是接线边界，禁止展示组件直接 import
  `backend.ts`、`lionRuntime.ts` 或建立外部项目的 store。
- `chat-shell` 使用纵向弹性布局：Header、可选 notice 区和可收缩的 Thread 依次排列，
  Thread Viewport 再以 column flex 将 Composer 推到窗口底部。禁止用“当前消息数量”推导
  固定高度，否则短会话会把 Composer 悬在窗口中部。

## 4. Validation & Error Matrix

| Condition | Renderer behavior |
| --- | --- |
| metadata response is non-2xx or invalid | keep chat transport usable and show a diagnostic metadata error |
| Provider configuration read is non-2xx or invalid | keep the settings surface usable and show a diagnostic metadata error |
| Provider write succeeds while metadata refresh is pending | resolve the write and close the settings surface; keep the later metadata result diagnostic |
| Provider/Thinking write fails | keep settings open and show the server detail |
| active run | disable Session, Provider, and Thinking mutations |
| `api_configured=false` and a prompt is sent | render an assistant error and clear the streaming state |
| `api_configured=false` on status refresh | open first-run settings once; do not reopen on every snapshot |
| 1280x720 or 2560x1440 | no document-level horizontal overflow; composer and approvals remain reachable |
| restored pane widths exceed the current display | clamp both panes and retain at least 360px for chat |
| search has no matching session | show an explicit local empty result without mutating canonical sessions |
| rename label is blank / over 80 characters | reject with 422 and keep the editor open |
| rename target is outside workspace or missing | return 404 without revealing cross-workspace existence |
| rename while a run is active | return 400 and leave canonical metadata unchanged |
| composer text starts with `/` | show filtered Skills list; selection writes the slash command without sending it |
| composer loses slash trigger or presses Escape | remove the popover DOM and retain normal composer focus behavior |
| short or empty transcript | composer bottom remains inside the viewport and below the readable transcript area |
| reduced motion | state remains legible with animations effectively disabled |

## 5. Good / Base / Bad Cases

- Good: a Provider save succeeds, metadata refreshes, and the user returns to the same
  assistant-ui Thread without creating a second chat store.
- Good: rename appends a `LabelEntry`, refreshes `/api/sessions`, and updates both sidebar
  and topbar without replacing the active assistant-ui Thread.
- Base: no prior sessions or Skills yields instructive empty copy and a usable composer.
- Bad: component `useState` owns a session title, API credentials are copied into status,
  history, logs, or error text, the settings form cannot read back its canonical values,
  `/` suggestions bypass assistant-ui keyboard handling, or Escape implicitly approves a
  blocking request.

## 6. Tests Required

- Vitest: strict metadata decoding, metadata actions, relative-time boundaries, and the
  existing protocol/runtime suite; assert that a successful Provider write resolves while
  an auxiliary metadata request remains pending, that Provider settings read back into a
  masked form with an explicit reveal action, and that sidecar assistant errors project as
  incomplete assistant messages.
- Electron Playwright: REST history to streamed response, 1280x720 and 2560x1440 overflow
  checks, both themes, screenshots for the desktop chat state, and a Composer bounding-box
  assertion proving the short-transcript layout remains bottom-reachable. The desktop chrome
  scenario also covers search, project disclosure, notification empty state, work-panel view
  selection, Provider settings, keyboard/pointer pane resizing, Composer focus styling,
  slash-triggered Skill selection, durable session rename, and closed-popover cleanup.
- Run `npm test`, `npm run typecheck`, `npm run build`, and all Playwright projects with one
  worker when real sidecar projects share machine resources.

## 7. Wrong vs Correct

**Wrong:** infer the Provider from an optional base URL, or load settings values only from
the status projection. A saved OpenAI configuration with an empty custom URL can restart as
the wrong Provider, and a settings reopen loses the key even though Python persisted it.

**Correct:** persist an explicit Provider kind, apply the default OpenAI endpoint when no
custom URL is stored, and read the complete Provider snapshot through a dedicated protected
REST route. Await canonical history before connecting WebSocket, then refresh auxiliary
metadata independently and surface its failure separately.

**Wrong:** verify missing-API behavior only with a fake REST/WebSocket harness.

**Correct:** keep the strict protocol unit test, and add a real preview Electron/sidecar
scenario that sends without credentials, observes the visible assistant error, verifies the
composer becomes usable again, saves settings, and reads them back after sidecar restart.

**Wrong:** rename only the visible row or build an ad-hoc `/` menu with independent key
handling. The title disappears after refresh and keyboard/IME behavior diverges from the
assistant-ui Composer.

**Correct:** append a canonical `LabelEntry`, refresh REST metadata, and let assistant-ui's
TriggerPopover own slash detection, selection, Escape, and Arrow-key behavior.
