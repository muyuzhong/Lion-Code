# 前端任务功能现状调研（2026-08-22）

本文件是设计的证据基线：所有条目均从当前源码验证，行号以本轮调研时的工作树为准。
后续实现前应复核行号漂移，结论失效时更新本文件。

## 1. 前端组件与职责

| 组件 | 职责 | 证据 |
| --- | --- | --- |
| `Sidebar.tsx` | 会话列表、新建会话、workspace 目录、Token 总量 | `frontend/src/components/chat/Sidebar.tsx:59-100` |
| `Header.tsx` | 连接状态、模型切换、主题、设置入口 | `frontend/src/components/chat/Header.tsx:57-96` |
| `ChatArea.tsx` | 消息流、空态 starter prompts、回到底部 | `frontend/src/components/chat/ChatArea.tsx:11-36` |
| `ChatInput.tsx` | 输入、流式时变停止按钮、`/plan` 快捷键 | `frontend/src/components/chat/ChatInput.tsx:22-48,75-83` |
| `MessageItem.tsx` | Markdown + 代码高亮 + 复制、错误卡片 | `frontend/src/components/chat/MessageItem.tsx:54-171` |
| `ToolView.tsx` | 工具卡片：状态徽标、参数摘要、展开看入参/输出 | `frontend/src/components/chat/ToolView.tsx:22-76,112-200` |
| `ApprovalModals.tsx` | 确认横幅 + Plan 审批弹窗（4 种选择） | `frontend/src/components/chat/ApprovalModals.tsx:12,64` |
| `SettingsModal.tsx` | Provider/API key/模型/thinking 档位 | 调用 `setThinkingLevel`（api.ts:87-95） |
| `ReasoningView.tsx` | 折叠思考卡片 | — |

会话列表项只显示 `sess.id.slice(0, 16)` + 时间（Sidebar.tsx:91），
`SessionSummary.messageCount` 后端已返回但未展示（types/chat.ts:36-41）。

## 2. REST API 面（后端已提供）

`lion_code/server/app.py:169-419`：

- `GET /api/health`（公开）、`GET /api/status`、`GET /api/messages`
- `GET /api/sessions`（按当前 cwd 过滤）、`POST /api/sessions/resume`、`POST /api/sessions/new`
- `GET /api/models`、`POST /api/config/provider`
- `GET /api/skills` → `SkillItem(name, description)`（app.py:404-408）**前端 api.ts 无对应调用**
- `POST /api/thinking`
- `WS /ws/chat`

`frontend/src/lib/api.ts` 只有 8 个函数，无 `fetchSkills`。

`ServerStatus.permission_mode`、`is_running` 已返回但 UI 未展示（types/chat.ts:22-34）。

## 3. WebSocket 协议现状

ClientAction 全集（chatProtocol.ts:14-28）：`prompt` / `steer` / `follow_up` / `continue` /
`compact` / `cancel` / `command` / `confirm_response` / `plan_approval_response`。

ServerEvent 全集（chatProtocol.ts:105-169）。reducer 中**被解码但直接忽略**的事件
（chatProtocol.ts:579-589）：

- `agent_end` / `turn_start` / `turn_end` / `session_agent_end`
- `queue_update`（steering / followUp 全量快照）
- `compaction_started` / `compaction_completed` / `compaction_start`
- `auto_retry_start`（attempt / maxAttempts / delayMs / errorMessage）
- `notice`

关键语义（`lion_code/server/bridge.py:152-154,182`）：

- 会话运行中发 `prompt` 会被拒（"会话正在运行，请使用 steer 或 follow_up action"）；
- `steer` / `follow_up` 作为排队的补充指令注入当前执行；
- 前端 `useLionChat` 已实现 `sendSteer` / `sendFollowUp` / `sendCompact` / `sendCommand` /
  `sendContinue`（useLionChat.ts:155-179），但 `App.tsx:22-32` 只接线了
  `sendMessage` / `sendCancel`；流式期间输入框只能取消（ChatInput.tsx:35-48）。

## 4. 后端能力 vs 前端呈现缺口

| 后端能力 | 证据 | 前端现状 |
| --- | --- | --- |
| Skill（`skill` 工具 + `/api/skills`） | `lion_code/capabilities/skill/capability.py:21-24`；由 agent 调用工具触发，不是用户命令 | 完全无呈现 |
| Subagent（按 agent 类型 / 按 skill 派生 MetaAgent） | `lion_code/capabilities/subagent/factory.py:44,53` | 仅表现为普通工具卡片（`tool_execution_*` 事件） |
| git_status | `lion_code/capabilities/git_status/` | 无任何呈现 |
| 会话删除 / 重命名 / 搜索 | 后端只有 list / resume / new（app.py:284-319） | 无 |
| steer / follow_up 队列 | bridge.py:152-154 | 协议与 hook 就绪，UI 未接线 |
| auto_retry / compaction 进度 | 事件已到前端，reducer 忽略 | 无提示 |
| permission_mode | status 已返回 | 未展示 |

## 5. 技术约束

- 前端栈：React + TypeScript + Tailwind + shadcn 风格组件 + react-markdown +
  react-syntax-highlighter（Prism，天然支持 `diff` 语言高亮，无需新依赖）。
- dist 产物随包发布（`lion_code/server/static/`），改前端需跑 `python scripts/build_frontend.py` 重建。
- WS/REST 都要求 capability 凭证（app.py:77-97），新增 API 调用必须走
  `authorizedFetch` / capability 协议头。
- PR 规范：一个 PR 一个职责，可独立回滚；>10 提交或 >20 文件需拆分。
