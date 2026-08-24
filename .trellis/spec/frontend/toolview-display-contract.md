# ToolView 展示契约（diff / ANSI / agent 卡片）

## 1. Scope / Trigger

触碰桌面 `ChatThread` 的 Tool part、`toolPresentation.ts` 或后端 edit 工具 diff 产出格式时必读。

## 2. 契约

### edit diff hunk（跨层格式依赖）

- 后端 `_generate_diff`（`lion_code/tools.py:78`）产出 `@@ -{n},{c} +{n},{c} @@` 头。
- 桌面 `pickResultFormat`（`desktop/src/renderer/src/toolPresentation.ts`）正则
  `/^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@/m` 依赖此格式。**改后端 hunk 格式必须同步
  桌面正则与 toolPresentation.test.ts 的格式锚定用例**，否则 edit 结果静默退化为纯文本。

### agent 卡片判定（曾踩坑）

- 必须以 `toolName === "agent"` 精确匹配。**禁止按 args 字段形状判定**
  （如"有 type/description 字符串字段就当 agent"）——MCP 工具完全可能带同名入参，
  会被劫持成 agent 卡片头部并隐藏参数摘要（PR④ 评审实测修掉的 R4 违反）。

### 工具类型分类耦合

- `pickResultFormat` 的分类关键字与判定顺序（agent → 命令 → 写入 → 编辑）
  是单一分类入口；未知工具一律回退纯文本。新增工具类型时先加分类单测再改实现。

### ANSI 解析

- 前端自有 SGR 解析器（`parseAnsiToSpans`，零依赖决策：现有依赖无 ANSI 能力，
  候选库 ansi-to-react/anser 超出需求）；非 SGR 序列（光标控制/OSC）剥离，
  单独 `\r` 折叠为换行（进度条覆写帧）；0 号纯黑前景提亮 `#767676`（深底可读性，
  有契约测试锁定）。error 态结果固定纯文本红字，不做 ANSI 渲染。

## 3. Tests Required

`desktop/tests/renderer/toolPresentation.test.ts` 维持：hunk 格式锚定、工具类型边界
（edit/replace/write/bash/agent/未知、前缀变体优先级）、ANSI 检测与 span 解析
（组合码/截断/空串/0 号色提亮）。
