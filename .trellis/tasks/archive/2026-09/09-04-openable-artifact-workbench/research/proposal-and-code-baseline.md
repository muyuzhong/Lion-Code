# 提案与当前代码基线

## 结论

本任务采用 `agents/notes/2026-08-30-maka-openable-artifact-workbench.md` 的 P0
切片：把 Lion 已经持久化的大工具结果和受约束的工作区文件投影为可打开的只读
资源。Git 审查工作台提案已在当前工作树完成，不在本任务重复实现。

## 提案证据

提案明确要求：

- 先复用 `ResultStore` 已生成的 `persisted_path`，不建设 Artifact DB、上传、删除、
  多客户端租约或通用预览注册表；
- ToolActivity 提供“在工作面板打开”，WorkPanel 只读展示文本/Markdown/unified diff；
- 后端每次打开重新 resolve/stat/read，并限制工作区边界、大小和编码；Renderer 不得
  直接读文件；
- 缺失、过大、二进制、编码失败和越界都要成为明确状态。

Maka 的 `ArtifactRecord` / `HostArtifactCoordinator` / Workbar 只能作为交互和边界
参考，不能原样引入 Lion 的会话/Runtime。Lion 没有对应的 session-scoped artifact
身份，也没有多客户端资源生命周期需求。

## Lion 当前路径

### 结果生成

`lion_code/tooling/result_store.py::ResultStore.process`：

1. 成功且非 `normal` 策略的结果超过 `threshold_bytes` 时写入默认
   `Path.home() / ".lion-code" / "tool-results"`；
2. 返回有界预览；
3. 在 `ToolResult.details` 中保留完整文件路径、原始 UTF-8 字节数和结果策略。

`lion_code/tooling/types.py::ToolResult`、`lion_code/core/tools.py::AgentToolResult`、
`lion_code/core/messages.py::ToolResultMessage` 已有结构化 details 通道。该任务只把
其中安全的资源引用投影到 UI，不改变结果策略、Sanitizer 或 Egress 顺序。

### REST / WebSocket

- `lion_code/server/app.py::get_messages` 当前从 canonical messages 组装
  `ChatMessageDTO`，工具结果只投影 `result` 和 `is_error`；需要增加可选 openable。
- 同一 `create_app` 已有本机 capability 依赖和 `/api/git/*` 只读路由模式；资源读取
  应沿用该依赖，不增加另一套授权。
- `desktop/src/renderer/src/backend.ts::LionRestClient` 已集中处理带 capability 的
  REST 请求和严格 guard；资源读取应加入这里。
- `desktop/src/shared/chat.ts::decodeServerEvent` / `reduceChatProtocol` 已是 WS
  唯一输入和消息状态归属点；工具完成事件应在此投影可选资源引用，不能让组件直接
  消费 raw event。

### 桌面展示

- `desktop/src/renderer/src/components/ToolActivity.tsx` 当前只能复制工具参数和结果，
  没有打开回调。
- `desktop/src/renderer/src/components/WorkPanel.tsx` 已有“文件”视图入口，但内容是
  空状态；它已经通过 `useLionRuntime` 接收运行时投影，可承接只读资源状态。
- `desktop/src/renderer/src/assistantRuntime.tsx::projectLionMessage` 是 Lion 消息
  转 assistant-ui part 的单一投影点。assistant-ui tool-call part 自带 UI-only
  `artifact` 字段，可承载最小 openable 引用；ChatThread 将打开回调注入 ToolActivity。

## 边界判断

### 首版允许

1. ResultStore `persisted_path`；
2. 明确文件工具的 `file_path`，且后端重新解析后位于当前工作区；
3. `.txt` / 普通文本、Markdown、unified diff 的 bounded UTF-8 read-only 展示。

### 首版拒绝

- 任意 `run_shell.command`、搜索 `path` 或未知工具字段推导出的路径；
- 当前工作区外的文件、目录、越界符号链接；
- 超过读取上限、二进制、非 UTF-8、已删除或读取竞态中的内容；
- 编辑、删除、上传、资源数据库和 Electron raw IPC。

## 相关规范

- 后端：`runtime-boundaries.md`、`desktop-sidecar.md`、`error-handling.md`、
  `secret-boundary.md`、`quality-guidelines.md`；
- 前端：`toolview-display-contract.md`、`desktop-assistant-runtime-contract.md`、
  `desktop-chat-experience.md`；
- 指南：`cross-layer-thinking-guide.md`、`code-reuse-thinking-guide.md`。
