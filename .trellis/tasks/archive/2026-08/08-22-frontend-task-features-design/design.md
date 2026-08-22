# 前端任务功能补充设计

证据基线：`research/frontend-current-state.md`（含两轮核查，file:line 均为调研时点）。
分层原则：P0 = 后端/协议已就绪、仅前端接线；P1 = 前端少量新代码；P2 = 需后端配合。

## 决策记录（grilling，2026-08-22）

用户已拍板（均采推荐项）。Round 1：

- D1 流式期间输入语义：Enter 默认 `follow_up` 排队，`steer`（立即改向）做成显式按钮。
  理由：steer 会改向正在执行的任务，误触代价高；排队是 Claude Code / Cursor 的成熟惯例。
- D2 子任务视图拆两半：本轮只做 `agent` 工具的结果卡片（前端 only）；实时进度依赖的
  `on_update` 通道后端未接线（核查证据见 research §6），接线改造归 P2-9。
- D3 PR 粒度：按职责聚合为 4 个前端 PR（见文末拆分计划），P2 三项后端另立任务。
- D4 Skills 交互：点击条目填入自然句式引用（"用 \<name\> 技能帮我："），用户补全后发送。
- D5 P2 项保持粗粒度，落地前另立设计任务细化契约。
- D6 测试策略：每个 PR 补协议层单测（reducer / api），UI 组件不强制。

Round 2：

- D7 排队消息呈现：消息流内带"排队中"徽标 + 输入框上方计数徽标，数据源统一为
  `queue_update` 快照；被消费转正式 UserMessage 后徽标消失。
- D8 转向按钮形态：次级图标按钮，仅 `isStreaming` 时出现在发送按钮旁，点击即按
  `steer` 发送当前输入；不做模式切换（避免忘记切回导致误转向）。
- D9 agent 结果卡片深度：头部（`agent · type · description` + 状态）+ 结果
  Markdown 渲染；prompt 沿用 ToolView 现有入参折叠区，不加专属折叠区。

Round 3（对照 deepseek-harness）：

- D10 Trajectory 分期：简版进 P1（独立 PR⑤）；完整版记为 P2-10 候选，
  待简版验证真实需求再立项。
- D11 运行统计行：做。本地打点的耗时类指标（无 per-request usage），
  随 PR③ 交付。
- D12 零后端小件全收：bash ANSI 终端卡片（PR④）、DocumentTitle（PR①）、
  reasoningDuration 思考耗时显示（PR③）。
- D13 P2 候选池（C4）只留档不立项，落地后按真实需求再议。

---

## P0-1 Skills 浏览

**现状**：后端 `GET /api/skills` 返回 `SkillItem(name, description)`（app.py:404-408），
前端 `api.ts` 无调用、无任何 UI。

**设计**：

- `api.ts` 新增 `fetchSkills(): Promise<SkillItem[]>`，走 `authorizedFetch`。
- UI 放 Sidebar footer 区（workspace 目录与 Token 消耗之间），可折叠"可用 Skills"
  区块：每条显示 `name` + 截断的 `description`。
- 点击条目把 `用 <name> 技能帮我：` 填入聊天输入框并聚焦，用户补全意图后发送，
  由 agent 自行调用 `skill` 工具（skill 是 agent 侧工具，不伪造"用户直接执行"语义）。
- 加载时机：与 status / sessions / models 一起在 `loadData` 的 `Promise.all` 拉取，
  失败静默降级为空列表。

**不做**：skill 参数表单、执行进度专属视图、启用/禁用管理。

---

## P0-2 运行中交互：排队输入与转向

**现状**：会话运行中发 `prompt` 被 bridge 拒绝（bridge.py:182），补充指令走
`steer` / `follow_up`（bridge.py:152-154，同一队列机制，区别在注入时机：steer 改向
当前执行、follow_up 等当前轮结束）。前端 hook 已实现 `sendSteer` / `sendFollowUp`
（useLionChat.ts:171-179）但 App.tsx 未接线；流式期间 Enter 被阻止（ChatInput.tsx:22-48）。
`queue_update` 事件携带 steering / followUp 全量快照，reducer 忽略（chatProtocol.ts:583）。

**设计**：

- `isStreaming` 时输入框保持可用，**Enter / 主发送按钮 = `follow_up` 排队**（D1）。
- **"立即转向"做显式次级按钮**：仅 `isStreaming` 时出现在发送按钮旁，点击把当前
  输入作为 `steer` 发送。
- `ChatProtocolState` 增加 `queue: { steering: string[]; followUp: string[] }`，
  reducer 处理 `queue_update`（全量快照直接替换）。
- 排队消息在消息流内以带"排队中"徽标的用户消息呈现（数据源 `queue_update` 快照，
  单一事实源，不做乐观 append）；被消费转为正式 UserMessage 后徽标消失
  （需让 reducer 处理 `message_start` 的 user 角色——当前直接忽略）。
- 排队徽标（输入框上方 `已排队 ×N`）作为辅助提示。

**不做**：排队撤销（需新协议 action）、自动判断 steer vs follow_up。

---

## P0-3 重试 / 压缩 / 运行状态提示

**现状**：`auto_retry_start/end`、`compaction_start/end` 已解码但 reducer 忽略
（chatProtocol.ts:584-587）；API 自动重试或上下文压缩时界面看似卡死。
`ServerStatus.permission_mode` 已返回未展示（types/chat.ts:26）。

**设计**：

- `ChatProtocolState` 增加 `runtimeNotice`（单值，后到覆盖先到）：
  - `auto_retry_start` → `{ kind: "retry", attempt, maxAttempts, delayMs, errorMessage }`
  - `compaction_start` / `compaction_started` → `{ kind: "compaction", reason }`
  - `auto_retry_end(success)` / `compaction_end(无错误)` → 清除；失败仍走现有 `failStreaming`。
- UI：ChatInput 正上方一条窄状态条（"API 错误，第 2/5 次重试（3s 后）…" /
  "正在压缩上下文（threshold）…"），zinc 弱提示样式。
- Header 增加 `permission_mode` 徽标（纯展示，数据已在 `status`）。

**不做**：手动重试按钮、压缩进度百分比（协议未提供）、重试历史。

---

## P0-4 会话列表信息量

**现状**：列表项只显示 `sess.id.slice(0, 16)` + 绝对时间（Sidebar.tsx:71-96）；
`messageCount` 已返回未显示。

**设计**：列表项第二行显示 `N 条消息` + 相对时间（"今天 14:32" / "3 天前"，
纯前端格式化，不引库）。保留 ID 截断为辅助标识（P2-7 标题落地后替换）。

**不做**：重命名、置顶/归档、分组。

---

## P1-5 文件修改 diff 高亮

**现状**：`_edit_file`（tools.py:86-106）的返回值本身携带 unified diff
（`_generate_diff` 产出 `@@ -n,x +n,y @@` + `- `/`+ ` 行）；前端 ToolView 用纯文本
`<pre>` 展示（ToolView.tsx:174-196）。`_write_file` 返回的是行号预览，不含 diff。
react-syntax-highlighter（Prism）原生支持 `diff` 语言，零新依赖。

**设计**：

- ToolView 展开区对判定为"修改代码"（edit/replace 类）的工具：检测 `result` 是否
  含 `@@ ... @@` hunk——是则用 `<SyntaxHighlighter language="diff">` 渲染
  （增行绿、删行红），否则回退纯文本。
- 创建/写入类工具保持现有纯文本预览（其结果非 diff 形态）。
- bash / 命令类工具（D12）：结果含 ANSI 转义序列时渲染为终端风格卡片
  （黑底等宽 + 颜色），实现优先复用现有依赖能力，必要时引入成熟 ANSI 渲染库。

**不做**：多 hunk 合并视图、行内语法高亮叠加、跳转编辑器。

---

## P1-6 子任务结果卡片

**现状**：subagent 通过单一 `agent` 工具暴露（internal.py:10-41），入参含
`description`（3-5 词任务描述）、`prompt`、`type`（explore / plan / general）。
UI 上与普通工具卡片无差别。实时进度不可行：`on_update` 通道没有任何工具接线
（research §6），`tool_execution_update` 实际不触发——进度接线归 P2-9。

**设计**：

- `toolName === "agent"` 的调用渲染为"子任务"卡片：头部显示
  `agent · <type> · <description>` + 状态徽标，正文把 result 按 Markdown 渲染
  （子代理产出多为结构化报告，纯 pre 可读性差）。
- `prompt` 全文仍走 ToolView 现有"输入参数"折叠区，不重复设计。

**不做**：实时进度（P2-9）、并行子任务树、子任务取消、依赖图。

---

## P2-7 会话标题 / 删除 / 搜索（需后端）

**现状**：后端只有 list / resume / new（app.py:284-319）；元数据含
id / startTime / messageCount / cwd，无标题；无删除接口。

**接口形态（实现任务中细化契约，D5）**：

- 标题：首条用户消息落地时后端把截断摘要（≤40 字符）写入会话元数据；
  `SessionSummaryItem` 增加 `title`。
- 删除：`DELETE /api/sessions/{id}`，仅非当前、非运行中会话；404 与"不存在"
  同构返回（沿 resume 的不泄漏存在性模式，app.py:303-306）。
- 搜索：title + 时间已全量在前端，纯前端过滤框。

**边界问题（实现前必须回答）**：删除对 workspace 过滤的影响；resume 已删会话的
错误路径；磁盘文件删除原子性。

---

## P2-8 git 状态面板（需后端）

**现状**：`capabilities/git_status` 存在但 web 端无呈现；REST 面无对应接口。

**接口形态**：`GET /api/git-status` 返回 branch / dirty 数 / ahead-behind。
前端 Sidebar footer 徽标（`main · 3 changes`），点击展开变更文件列表。

**边界问题**：大仓库性能（capability 是否有缓存）；无 git 仓库时降级展示。

---

## P2-9 subagent 进度接线（需后端）

**现状**：`tool_execution_update` 的进度机制（core/loop.py:405-470 的 `on_update`
队列）已就绪，但所有工具（含 `agent` / `skill`）都未调用 `on_update`，事件从不触发。

**接口形态**：`agent` 工具执行期间周期性调用 `on_update` 上报子代理中间产出
（当前步骤 / 累计输出摘要）。前端 P1-6 卡片预留进度区，事件到达即显示。

**边界问题**：进度粒度与频率（避免刷屏）；子代理取消时进度通道的关闭语义。

---

## P1-7 Trajectory 轨迹视图（简版，D10）

**现状**：Lion 无任何执行轨迹呈现；会话 entry 自带服务端时间戳
（`core/session/entries.py:29-33`），但事件流无时间戳、无 request 级元数据。
对照 deepseek-harness 的 Trajectory 插件（`research/deepseek-harness-frontend-inventory.md`）。

**设计**（零后端，前端本地数据）：

- 入口：Header 增加"轨迹"按钮，打开**右侧滑出面板**（Sheet，不做三栏布局重构）。
- 数据源两段拼合：
  - 历史：`/api/messages` + 会话 entry 时间戳（消息级：用户/助手/工具结果，
    含状态与耗时推导）；
  - 实时：WS 事件流前端本地打点（`performance.now()`），覆盖流式期间的事件。
- 呈现：纵向时间线——每行 = 事件类型图标 + 摘要 + 耗时条（相对行宽比例）；
  行类型：用户消息 / 助手消息 / 工具调用（含状态色）/ 压缩 / 自动重试；
  点行展开详情（入参出参复用现有折叠渲染）。
- 联动：ToolView 卡片增加"检查"入口，打开轨迹面板并滚动定位到该调用
  （对应 deepseek 的 inspectCall 模式）。

**不做**（完整版归 P2-10）：后端事件持久化与分页、request inspection
（system prompt / usage / retry / prompt diff）、Network 式横向时间线交互
（拖选/缩放）、TTFT 与解码速率。

---

## P1-8 运行统计行（D11）

**现状**：`ChatMessage.reasoningDuration` 字段存在但 UI 未用；事件无时间戳、
无 per-request usage。deepseek 的 StatsLine 有 turns/steps/LLM 耗时/工具耗时/
TTFT/解码速率，Lion 数据面只支持耗时类。

**设计**：

- ChatInput 上方（状态条同行区域）显示：当前会话累计——turn 步数、
  LLM 耗时（message_start→message_end 累计）、工具耗时
  （tool_execution_start→end 累计）；本地打点，`ChatProtocolState` 增加
  `metrics` 字段由 reducer 累计。
- ReasoningView 折叠头显示 `reasoningDuration`（已有字段）格式化的思考耗时。

**不做**：TTFT、解码速率、token 速率（需后端 usage 事件，归 P2 候选池）。

---

## P2-10 Trajectory 完整版（需后端，D10 记录不立项）

**接口形态（立项时细化）**：后端持久化细粒度执行事件（含 request 级
usage / retry / prompt 变更）+ 分页拉取 API；前端在 P1-7 面板上增加
Network 式横向时间线与 request inspector。

**边界问题**：事件存储体积与保留策略；与现有 entry JSONL 的关系
（扩展 entry 类型 vs 独立流）；分页窗口语义。

**触发条件**：P1-7 简版落地且用户实际使用后确认需要历史细粒度回溯。

---

## P2 候选池（D13：留档不立项）

以下均需后端配合或大重构，仅记录防止丢失：

- `@` 文件候选菜单（需后端文件列表 API）；
- TodoPanel 任务清单（需后端 todo 能力，Lion 无）；
- ContextMeter 上下文压力条（需当前 prompt token 数）；
- 图片附件上传（需 WS 协议扩展；WireMessage 已支持 image block 但无上传通道）；
- 消息级反馈 / fork 分叉（需后端）；
- 三栏 DetailsPanel 布局（重构成本高，ToolView 展开已覆盖详情需求）。

## 测试策略（D6）

- 每个 PR 在 `frontend` 跑 `npm test`（vitest）：
  - PR①：`api.ts` 的 `fetchSkills`（协议契约级）。
  - PR②：`chatProtocol.test.ts` 扩展 `queue_update` reducer 行为、user 角色
    `message_start` 的入流转换。
  - PR③：`runtimeNotice` 与 `metrics` 累计相关 reducer 用例。
  - PR④：diff / ANSI 检测函数的纯函数单测。
  - PR⑤：轨迹事件折叠器（历史 + 实时打点合并）的纯函数单测。
- UI 组件渲染测试不强制（项目无先例，不引入维护成本）。
- 全部 PR 交付需跑 `python scripts/build_frontend.py` 更新随包 dist
  （服务端启动强校验 index.html，app.py:460-464）。

## PR 拆分计划（D3 + D10~D12：5 个前端 PR + 后端任务）

| PR | 内容 | 触碰面 | 回滚点 |
| --- | --- | --- | --- |
| ① 信息展示 | P0-1 Skills 浏览 + P0-4 列表信息量 + permission_mode 徽标 + DocumentTitle | Sidebar / Header / api.ts / App | 纯展示，revert 即消失 |
| ② 运行中交互 | follow_up 排队 + steer 显式按钮 + 队列呈现（D7/D8） | ChatInput / chatProtocol / useLionChat / App | revert 后回到"流式只可取消" |
| ③ 运行状态提示 | auto_retry / compaction 状态条 + 统计行 + reasoningDuration（P0-3 + P1-8） | ChatInput / ReasoningView / chatProtocol | 纯提示，revert 即消失 |
| ④ ToolView 增强 | P1-5 diff 高亮 + bash ANSI 卡片 + P1-6 agent 结果卡片 | ToolView | 非 edit/bash/agent 工具不受影响 |
| ⑤ Trajectory 简版 | P1-7 右侧滑出轨迹面板 + 工具卡片"检查"联动 | 新组件 / Header / ToolView | 独立面板，revert 即消失 |

- ①②③ 互不触碰同一状态可并行；④ 独立，内部顺序：diff → ANSI → agent 卡片；
  ⑤ 依赖 ④ 的 ToolView 改动落位后基于其加"检查"入口，排最后。
- P2-7 / P2-8 / P2-9 / P2-10 各自另立任务：先评审后端接口契约，再拆前后端 PR；
  P2 候选池（D13）不立项。
