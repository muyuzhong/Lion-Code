# 实现计划

## 阶段 1：后端安全读取与投影

- [x] 阅读并对照当前 server model、session message 序列化和现有 API 测试 fixture。
- [x] 新增 openable resource 的路径投影、根目录检查、字节上限、UTF-8/二进制和
      stat 竞态处理；不新增通用资源注册抽象。
- [x] 将 `ToolCallDTO.openable` 接入 `/api/messages`，新增受 capability 保护的
      `/api/resources/open` 响应。
- [x] 为允许路径、越界/符号链接、缺失/目录/过大/二进制/编码失败/changed 和历史
      details 投影增加最小后端测试。

## 阶段 2：协议与运行时投影

- [x] 扩展 shared chat 的 optional openable/artifact 合同和严格 decoder；保留旧 wire
      消息兼容。
- [x] 增加 REST client response guard 和资源读取方法。
- [x] 在 `LionAssistantRuntimeAdapter` 中加入资源状态、请求代数、session reset 和
      reload 逻辑，覆盖乱序请求不能覆盖当前资源。
- [x] 在 `projectLionMessage` / `ChatThread` / `ToolActivity` 之间传递数据与 callback，
      不让展示组件直接读取文件或依赖 backend。

## 阶段 3：WorkPanel 与验证

- [x] 把文件视图从占位改为只读资源视图，复用现有 Markdown/diff/pre 样式；错误状态
      和元数据可见，未实现编辑/系统打开。
- [x] 增加/更新 `tests/application`、`tests/server` 与 `desktop/tests/renderer` 的
      targeted coverage。
- [x] 运行受影响 Python tests、desktop Vitest、desktop `typecheck`/`build`，再运行
      `git diff --check`；如遇 baseline 失败，记录与本任务变更的归因，不扩大修复范围。
- [x] 由主会话审查 diff、检查未跟踪 `agents/` 用户笔记未被改动；实现完成后再按
      Trellis 3.4 单独确认是否需要提交，未经明确授权不 push/merge。

## 验证记录

- Python targeted：`46 passed, 1 skipped`。
- Python 全量（排除 Windows 无法收集的 `tests/benchmarks`）：`947 passed, 2 skipped, 10 subtests passed`。
- Desktop：`npm test` 为 `13` 个测试文件、`72` 个测试通过；`npm run typecheck`、`npm run build`、`python -m compileall -q lion_code tests` 和 `git diff --check` 通过。
- Python 全量直接执行仍受既有 `tests/benchmarks` 收集错误阻断：Windows 没有 `os.geteuid`，且 benchmark 包导入路径不可用；排除后回归通过。

## 预期修改面

生产代码集中在：

- `lion_code/application/` 的单一资源读取/投影函数；
- `lion_code/server/models.py`、`lion_code/server/app.py`；
- `desktop/src/shared/chat.ts`、`desktop/src/renderer/src/backend.ts`、
  `desktop/src/renderer/src/lionRuntime.ts`、`assistantRuntime.tsx`、`ChatThread.tsx`、
  `components/ToolActivity.tsx`、`components/WorkPanel.tsx`。

测试只覆盖上述行为边界，不修改 ResultStore 策略、ToolRuntime、Sanitizer、Egress 或
Git 审查功能。

## 完成定义

代码、测试和 targeted checks 达到 PRD 验收条件；工作树中的用户既有 `agents/` 内容
保持原样；不以提交、推送或合并作为本任务的隐含完成条件。
