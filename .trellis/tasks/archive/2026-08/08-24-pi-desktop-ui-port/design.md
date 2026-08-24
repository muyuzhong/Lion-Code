# PI-Desktop UI 移植：设计

## Design Boundary

本任务采用“忠实复现上游展示层 + Lion 行为适配”，而不是重新设计，也不是整仓 Renderer 替换。

```text
Python sidecar / REST / WS                       unchanged
        │
LionAssistantRuntimeAdapter                     unchanged
        │
assistant-ui Runtime and primitives             unchanged
        │
Lion presentation components matching PI source replace
        │
PI-inspired semantic tokens and CSS             replace
```

`WorkspaceShell` 继续拥有主题、面板开关和草稿种子；`ChatThread` 继续消费 assistant-ui primitives；所有动作仍经 `useLionRuntime()` 进入 `LionAssistantRuntimeAdapter`。

会话重命名是唯一新增的跨层动作：`POST /api/sessions/rename` 进入
`LionCodingSession`，由 `SessionRuntime` 通过当前 `SessionRecorder` 或
`SessionRepository` 追加 `LabelEntry`。这样标题保持 Python canonical，避免 Renderer
本地标题在刷新后丢失，也不会把重命名塞入聊天 WebSocket 协议。

## Source Selection

视觉基准固定为 PI-Desktop commit `e56a3ed179a728723bde050f941e896922d67590`。优先参考：

- `Sidebar.tsx`、`ConversationTopbar.tsx`：项目/会话层级、活动状态和密度。
- `ChatSurface.tsx`、`ChatTranscript.tsx`：连续消息流和工具活动布局。
- `Composer.tsx`：浮动输入区、运行态与模型/权限信息排布。
- `PermissionCard.tsx`、`PlanApprovalBar.tsx`、`ToolDetails.tsx`、`TurnOutcomeCard.tsx`：编码 Agent 状态表达。
- `tokens.css`、`chat-shell.css`、`messages.css`、`composer.css`、`sidebar-threads.css`：Token、间距、边框、背景和层次。

这些组件分别达到 155–2480 行并直接依赖 PI store/API/shared types，因此不能直接复制其状态耦合实现；展示结果仍须忠实匹配上游。布局与 Token 直接复用，业务 props 由 Lion 类型重新定义。

## Renderer Shape

保持入口文件和 Runtime 文件不变，在 `desktop/src/renderer/src/components/` 下建立小型展示层：

```text
components/
├─ DesktopSidebar.tsx
├─ ConversationTopbar.tsx
├─ ToolActivity.tsx
├─ ApprovalSurface.tsx
├─ ComposerChrome.tsx
└─ WorkPanel.tsx

styles/
├─ tokens.css
├─ shell.css
├─ transcript.css
├─ composer.css
└─ overlays.css
```

组件仅接受 primitive props/callback，不 import `backend.ts`、`lionRuntime.ts` 或任何 PI package。`WorkspaceShell` 与 `ChatThread` 是唯一接线层。

## Mapping

| PI-Desktop concept | Lion source | Rule |
| --- | --- | --- |
| project/session tree | `snapshot.sessions`, current workspace | 展示映射，不新增 project store |
| transcript messages | assistant-ui `ThreadPrimitive` | 不复制 PI transcript reducer |
| tool activity | assistant-ui `MessagePrimitive.Parts` + `toolPresentation.ts` | 保持 `toolCallId` 语义 |
| composer running state | assistant-ui `ComposerPrimitive` + `snapshot.protocol` | 保持 send/cancel/queue 动作 |
| work panel shell | Lion local open/close state | 复现右栏与空资源态，不伪造资源 Runtime |
| permissions | `snapshot.protocol.confirmRequest` | safe action 默认不变 |
| plan approval | `snapshot.protocol.planApprovalRequest` | `keep-planning` 默认不变 |
| model/thinking | Python REST metadata | 仍由设置表单写回 Python |

## Styling

- 使用 Lion-owned CSS custom properties，值直接对齐 PI 的背景、尺寸、对比度、层级和圆角。
- 不引入 Tailwind；避免为了复制 className 而增加构建系统。
- `styles.css` 改为聚合入口，具体规则拆到 `styles/`，降低单文件冲突与后续替换成本。
- 主题使用 `document.documentElement.dataset.theme`，延续当前 `lion-theme` 偏好键。
- 动画只用于 hover、展开和状态过渡，`prefers-reduced-motion` 下禁用。

## Dependency Decision

允许增加 `lucide-react` 作为唯一 UI 依赖，用于 PI 风格的稳定图标体系。不得引入 PI workspace packages、Zustand、Tailwind 或第二套聊天/组件 Runtime。

## Isolation and Delivery

- 从当前已提交 tip `ee6095f` 创建独立 worktree/分支 `muyuzhong/pi-desktop-ui-port`。
- 当前主工作树未提交的 `styles.css` 保持原样，不 stash、不 reset、不复制进新分支。
- 新任务 PR 依赖桌面 cutover 内容；上游合并后再 rebase 到 `master`，最终 PR target 为 `master`。

## Rollback

本任务主要修改 Renderer 展示层和一个图标依赖，并新增一条 append-only 会话标题
REST 链路。回滚该提交会恢复旧 UI 并移除重命名入口；既有 Session JSONL 中未知的
`LabelEntry` 已属于 Core schema，历史与聊天协议、sidecar 启动和打包链路不受影响。
