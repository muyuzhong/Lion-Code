# deepseek-harness Web 前端功能清点（2026-08-22）

对照参考项目 `D:\harness agent\deepseek-harness`（pnpm monorepo，插件化 cordis +
slot 三栏单页应用），用于推导 Lion 前端的功能补充候选。路径均为该仓库内路径。

## 结构

- `apps/web/src/main.ts` 薄壳 → `packages/client/web`（AppRoot/app-shell）→
  `packages/bundle/web-app` 依赖清单即启动插件图。
- `packages/client/ui-layout/.../AppFrame.tsx`：三栏（侧栏 | 会话 | 详情栏），
  声明 `sidebar`/`conversation`/`details`/`shell.overlay` slot。
- `ui-conversation/.../ConversationSession.tsx`：会话头含**视图 Tab 环**
  （`conversation.view` slot）：Chat(0) + Trajectory(10)。

## Trajectory 轨迹视图（重点）

- 位置：`packages/client/ui-trajectory/`（独立插件，纯浏览器端，无服务）。
- 数据：从共享 Session 的**原始事件窗口**自行折叠为 TrajectorySnapshot
  （`trajectory-snapshot-builder.ts`），与 Chat 是同一事件流的两个投影；
  历史经 `session.loadOlder()` 分页。
- 呈现：工具栏（时间线模式四档：sequence/duration/actual/time + 折叠 + 搜索）→
  `TrajectoryTimeline.tsx`（Chrome Network 风横向条形，assistant span 拆
  TTFT/decode 两段，拖选聚焦/缩放/平移）→ `TrajectoryTable.tsx`（tanstack
  virtual 虚拟化账本，Turn 粗分隔 + Step 标记，点行开 inspector：token usage /
  duration / Input / Output / Timing；请求分隔行含 retry/provider/model，
  prompt 变更用 `structuredPatch` 渲染 diff）。
- 互通：Chat 里工具调用 Inspect 按钮跳转 Trajectory 定位（`apply.ts` inspectCall）。

## 会话数据层（packages/client/runtime/src/client/sessions/）

- `assistant-timing.ts`：每步 TTFT + decode 时长 fold，Chat/Trajectory 共用。
- `request-inspection.ts`：RequestView——provider/model、完整 system prompt、
  随请求工具目录、usage、retry/maxRetries/retryDelayMs、prompt 变更前后快照。
- `tool-call-tree.ts`：递归工具调用树（深度上限 256）。
- `steering-history.ts` / `queue-mirror.ts`：插话身份与排队预览。
- `lineage.ts` / `subagent-lineage.ts`：会话血缘 / subagent 子树。

## Chat 视图功能件

| 功能件 | 位置 | 说明 |
| --- | --- | --- |
| StatsLine | `ui-conversation/.../chat/StatsLine.tsx` | composer 上统计行：turns/steps、LLM 耗时、工具耗时、TTFT、decode 速率 |
| turn-metrics | `chat/turn-metrics.ts` | 单 turn 尾部 TTFT / tokens-per-second |
| ReasoningRow | `chat/ReasoningRow.tsx` | 思考过程独立折叠行 |
| 工具树 | `ui-tool/.../ToolCallTree.tsx` + `toolviews/` | 递归树 + 按工具定制行（bash-sample 终端卡片渲染 ANSI、file-mutation、read、search、todo、web 行） |
| DetailsPanel | `skeleton/DetailsPanel.tsx` | 右栏：工具参数 JSON + 结果原文，bash 为终端卡片 |
| QueueDock | `queue/QueueDock.tsx` | 排队消息 dock：逐条编辑/发送/删除 |
| TodoPanel | `skeleton/TodoPanel.tsx` | composer 上 Todo 清单条（勾选/折叠） |
| ContextMeter | `skeleton/ContextMeter.tsx` | 上下文压力/令牌计量条 |
| ApprovalPanel | `skeleton/ApprovalPanel.tsx` | 工具审批接管输入框 |
| 消息操作 | `chat/MessageIconActions.tsx` | 复制、**fork（从此消息分叉会话）**、时钟 |
| 消息反馈 | `ui-message-feedback` | 每条助手消息 Like/Dislike + 备注 |
| 产出文件 | `ui-deliverables/.../ProducedFiles.tsx` | 回复末尾产出文件行 + 正文引用可点开 |
| 图片附件 | `ui-attachment` | 输入缩略栏/画廊/灯箱/拖放 |
| 输入触发 | `ui-input-trigger` | `/` 与 `@` 光标处候选菜单（skill 候选来自 skill.list RPC） |

## 其他

- GoalBar（`ui-goal`）：composer 上目标条，阶段/暂停/恢复/编辑。
- JobListAction（`ui-jobs`）：会话头后台任务列表。
- WorkflowRunPanel（`ui-workflow-run`）：持久化工作流运行重建为 Chat 节点。
- SubagentCatalog（`ui-subagent`）：会话头 subagent 目录树 + 只读 composer。
- Settings 分区（`ui-settings-*`）：General/Models/Plugins 多区设置。
- WorkspaceBrowser（`ui-workspace`）：树/平铺/搜索/排序的会话浏览器。
- DocumentTitle（`client/web/src/DocumentTitle.tsx`）：会话标题写入浏览器标签页。

## 与 Lion 的数据面差异（决定可行性）

| deepseek 数据 | Lion 现状 | 影响 |
| --- | --- | --- |
| 原始事件流 + loadOlder 分页 | WS 实时事件（无时间戳字段）+ `/api/messages`（折叠后消息） | 历史轨迹只能到消息级 |
| 会话 entry 含服务端时间戳 | ✅ `core/session/entries.py:29-33`（BaseSessionEntry.timestamp）+ compaction/model_change 等 9 种 entry | 消息级历史时间线可行 |
| request-inspection（system prompt/usage/retry/prompt diff） | ❌ 无对应事件/存储 | 细粒度轨迹需后端新增 |
| assistant-timing（TTFT/decode） | ❌ 事件无时间戳 | 流式期间可前端本地打点近似 |
| per-request usage | ❌（仅会话累计 input/output tokens） | 统计行降级为耗时类指标 |
