# PI-Desktop UI 移植：设计

## Design Boundary

本任务采用“视觉结构移植 + Lion 行为适配”，而不是整仓 Renderer 替换。

```text
Python sidecar / REST / WS                       unchanged
        │
LionAssistantRuntimeAdapter                     unchanged
        │
assistant-ui Runtime and primitives             unchanged
        │
Lion PI-style presentation components           replace
        │
PI-inspired semantic tokens and CSS             replace
```

`WorkspaceShell` 继续拥有主题、面板开关和草稿种子；`ChatThread` 继续消费 assistant-ui primitives；所有动作仍经 `useLionRuntime()` 进入 `LionAssistantRuntimeAdapter`。

## Source Selection

视觉基准固定为 PI-Desktop commit `e56a3ed179a728723bde050f941e896922d67590`。优先参考：

- `Sidebar.tsx`、`ConversationTopbar.tsx`：项目/会话层级、活动状态和密度。
- `ChatSurface.tsx`、`ChatTranscript.tsx`：连续消息流和工具活动布局。
- `Composer.tsx`：浮动输入区、运行态与模型/权限信息排布。
- `PermissionCard.tsx`、`PlanApprovalBar.tsx`、`ToolDetails.tsx`、`TurnOutcomeCard.tsx`：编码 Agent 状态表达。
- `tokens.css`、`chat-shell.css`、`messages.css`、`composer.css`、`sidebar-threads.css`：Token、间距、边框、背景和层次。

这些组件分别达到 155–2480 行并直接依赖 PI store/API/shared types，因此只迁移结构、样式规则与纯展示片段；业务 props 由 Lion 类型重新定义。

## Renderer Shape

保持入口文件和 Runtime 文件不变，在 `desktop/src/renderer/src/components/` 下建立小型展示层：

```text
components/
├─ DesktopSidebar.tsx
├─ ConversationTopbar.tsx
├─ ToolActivity.tsx
├─ ApprovalSurface.tsx
└─ ComposerChrome.tsx

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
| permissions | `snapshot.protocol.confirmRequest` | safe action 默认不变 |
| plan approval | `snapshot.protocol.planApprovalRequest` | `keep-planning` 默认不变 |
| model/thinking | Python REST metadata | 仍由设置表单写回 Python |

## Styling

- 使用 Lion-owned CSS custom properties，把 PI 的尺寸、对比度、层级和圆角映射到 Lion 名称。
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

本任务只修改 Renderer 展示层和一个图标依赖。回滚该 PR 即恢复当前 Cherry 风格 UI；assistant-ui、协议、sidecar、Session 文件和打包链路不受影响。
