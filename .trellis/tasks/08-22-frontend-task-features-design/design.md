# 前端任务功能补充设计

证据基线：`research/frontend-current-state.md`（下文引用行号为该文件记录的调研时点）。
分层原则：P0 = 后端/协议已就绪、仅前端接线；P1 = 前端少量新代码；P2 = 需后端配合。

---

## P0-1 Skills 浏览

**现状**：后端 `GET /api/skills` 返回 `SkillItem(name, description)`（app.py:404-408），
前端 `api.ts` 无调用、无任何 UI。用户无法得知有哪些可用技能。

**设计**：

- `api.ts` 新增 `fetchSkills(): Promise<SkillItem[]>`，走 `authorizedFetch`。
- UI 放 Sidebar 底部 footer 区（workspace 目录与 Token 消耗之间），一个可折叠的
  "可用 Skills" 区块：每条显示 `name` + 截断的 `description`。
- 点击条目把引用文本填入聊天输入框（如 `请使用 skill 工具执行 <name>：`），
  用户补全意图后发送，由 agent 自行调用 `skill` 工具。**不伪造"用户直接执行
  skill"语义**（skill 是 agent 侧工具，见 R5）。
- 数据加载：与 status / sessions / models 一起在 `loadData` 的 `Promise.all` 拉取，
  失败静默降级为空列表（Skills 非关键路径）。

**不做**：skill 参数表单、skill 执行进度专属视图、skill 启用/禁用管理。

---

## P0-2 流式期间 steer / follow_up 输入

**现状**：会话运行中发 `prompt` 被 bridge 拒绝（bridge.py:182），补充指令应走
`steer` / `follow_up`（bridge.py:152-154）。前端 hook 已实现 `sendSteer` /
`sendFollowUp`（useLionChat.ts:171-179），但 App.tsx 未接线；ChatInput 流式期间
Enter 被阻止、发送按钮变停止（ChatInput.tsx:22-48）。`queue_update` 事件携带
steering / followUp 全量快照，reducer 直接忽略（chatProtocol.ts:583）。

**设计**：

- ChatInput 在 `isStreaming` 时保持可输入：Enter 发送走 `sendSteer`（改变当前
  执行方向，最贴近用户直觉）；停止按钮保留不变。
- 发送 steer 后本地 append 一条用户消息（带"转向"小徽标区分普通消息），
  复用 `dispatch({ type: "append_user" })` 路径，`ChatMessage` 增加可选
  `queued?: "steer"` 标记。
- `ChatProtocolState` 增加 `queue: { steering: string[]; followUp: string[] }`，
  reducer 处理 `queue_update`（事件为全量快照，直接替换）。
- 输入框上方显示排队徽标：`已排队补充指令 ×N`，数据来自 `queue`。
- `follow_up` 的显式入口本轮不建 UI（无撤销协议，入口越多越易误操作）；
  协议能力保留，入口扩展与撤销一起作为后续项。

**不做**：排队撤销（需新协议 action）、自动判断 steer vs follow_up、多队列管理。

---

## P0-3 重试 / 压缩 / 运行状态提示

**现状**：`auto_retry_start/end`、`compaction_start/end` 已解码但 reducer 忽略
（chatProtocol.ts:584-587）；API 报错自动重试或上下文压缩时界面看似卡死。
`ServerStatus.permission_mode` 已返回未展示（types/chat.ts:26）。

**设计**：

- `ChatProtocolState` 增加 `runtimeNotice`（单值，后到覆盖先到）：
  - `auto_retry_start` → `{ kind: "retry", attempt, maxAttempts, delayMs, errorMessage }`
  - `compaction_start` / `compaction_started` → `{ kind: "compaction", reason }`
  - `auto_retry_end(success)` / `compaction_end(无错误)` → 清除
  - 失败路径仍走现有 `failStreaming`，不重复提示。
- UI：ChatInput 正上方一条窄状态条——"API 错误，第 2/5 次重试（3s 后）…" /
  "正在压缩上下文（threshold）…"，样式同 zinc-500 弱提示，可自动消失。
- Header 增加当前 `permission_mode` 徽标（数据已在 `status` 中，纯展示）。

**不做**：手动重试按钮、压缩进度百分比（协议未提供）、重试历史列表。

---

## P0-4 会话列表信息量

**现状**：列表项只显示 `sess.id.slice(0, 16)` + 绝对时间（Sidebar.tsx:71-96）；
`messageCount` 已返回未显示。会话无标题（标题需后端在会话元数据中落盘首条用户
消息摘要，归 P2-7）。

**设计**：

- 列表项第二行显示 `messageCount` 条消息 + 相对时间（"今天 14:32" / "3 天前"，
  纯前端格式化，不引库）。
- 保留 ID 截断作为辅助标识（等 P2-7 标题落地后替换为标题）。

**不做**：会话重命名（无后端）、置顶/归档、分组。

---

## P1-5 文件修改 diff 渲染

**现状**：write/edit/replace 类工具的执行输出是 `<pre>` 纯文本
（ToolView.tsx:174-196）；项目已依赖 react-syntax-highlighter（Prism），
Prism 原生支持 `diff` 语言，零新依赖。

**设计**：

- ToolView 展开区对 `getToolConfig` 判定为"创建/写入"与"修改代码"的工具，
  检测 `result` 是否含 diff 形态（以 `+` / `-` 起始的行为主体）：
  是 → 用 `<SyntaxHighlighter language="diff">` 渲染（增行绿、删行红）；
  否 → 回退现有纯文本，不做格式猜测。
- 实现前先核实 write/edit 工具的实际输出格式（`lion_code/tooling/` 内 str_replace
  系工具）；若输出本身不含 diff 文本，则此 PR 顺带让前端按入参构造
  "旧文本→新文本"的最小展示（入参 `old_string` / `new_string` 已在 `args` 中），
  仍不引新依赖。

**不做**：文件级多 hunk 合并视图、行内语法高亮叠加、跳转编辑器。

---

## P1-6 子任务（subagent）进度视图

**现状**：`capabilities/subagent` 可按 agent 类型 / skill 派生 MetaAgent
（factory.py:44,53），但 UI 上只是普通工具卡片；`agent_start` / `agent_end` 事件
被忽略（chatProtocol.ts:579-582）。

**设计**：

- 不新增后端事件（R6）。识别 subagent 类工具调用（按 `toolName` 白名单，实现时
  从 `SubagentFactory.create_for_agent_type` 注册的工具名取），在 ToolView 卡片
  内渲染"子任务"区域：状态行（运行中/完成/失败）+ `tool_execution_update` 的
  `partialResult` 流式摘要（限高滚动，等宽字体）。
- 即：把现有 `partialResult` 数据从"被覆盖的中间值"升级为"子任务实时日志"，
  协议不动。
- 结构化子代理事件流（子代理自己的 toolcall / text 事件独立转发）列为可选扩展：
  需后端 bridge 改造，另行立任务设计。

**不做**：并行子任务树、子任务取消按钮、子代理间依赖图。

---

## P2-7 会话标题 / 删除 / 搜索（需后端）

**现状**：后端只有 list / resume / new（app.py:284-319）；会话元数据含
id / startTime / messageCount / cwd，无标题；无删除接口。

**接口形态（实现任务中细化契约）**：

- 标题：会话首条用户消息落地时，后端把截断摘要（≤40 字符）写入会话元数据；
  `SessionSummaryItem` 增加 `title`。前端列表项主文案换 title。
- 删除：`DELETE /api/sessions/{id}`，仅允许删除非当前、非运行中的会话；
  删除范围 = 元数据 + 会话文件（确认 `core/session` 存储结构后定）；
  404 与"不存在"返回同构错误（沿 resume 的不泄漏存在性模式，app.py:303-306）。
- 搜索：数据（title + 时间）已全量在前端，纯前端过滤框，无后端改动。

**边界问题（实现前必须回答）**：删除是否影响 `list_sessions` 的 workspace 过滤；
resume 一个被删会话的错误路径；磁盘文件删除的原子性。

---

## P2-8 git 状态面板（需后端）

**现状**：`capabilities/git_status` 存在但 web 端无呈现；REST 面无对应接口。

**接口形态**：`GET /api/git-status` 返回 branch / dirty 数 / ahead-behind，
数据来自现有 capability。前端 Header 或 Sidebar footer 显示徽标
（如 `main · 3 changes`），点击展开变更文件列表（path + status）。

**边界问题**：大仓库性能（capability 是否已有缓存）；无 git 仓库时的降级展示。

---

## PR 拆分计划

| PR | 内容 | 依赖 | 回滚点 |
| --- | --- | --- | --- |
| A | P0-1 Skills 浏览 | 无 | 纯前端，revert 即消失 |
| B | P0-2 steer 输入 + queue 展示 | 无 | 纯前端；revert 后回到"流式只可取消" |
| C | P0-3 重试/压缩状态条 | 无 | 纯前端 |
| D | P0-4 列表信息量 + permission_mode 徽标 | 无 | 纯前端 |
| E | P1-5 diff 渲染 | 无 | 纯前端，检测失败自动回退纯文本 |
| F | P1-6 子任务进度 | 无 | 纯前端，非 subagent 工具不受影响 |
| G | P2-7 会话标题+删除+搜索 | 后端先行 | 后端接口与前端分两个 PR |
| H | P2-8 git 状态面板 | 后端先行 | 同上 |

顺序建议：A/B/C/D 可并行（互不触碰同一状态）；E/F 在其后（同改 ToolView，
E、F 之间按先 E 后 F 串行避免冲突）；G/H 待后端接口设计评审后另立任务。

每个前端 PR 交付后需跑 `python scripts/build_frontend.py` 更新随包 dist 产物
（服务端启动强校验 index.html 存在，app.py:460-464）。
