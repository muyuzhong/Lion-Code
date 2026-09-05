# 实现可打开产物工作台

## Goal

让用户可以从工具活动中打开已经存在的完整工具结果或明确返回的工作区文件，
在桌面 WorkPanel 中以只读方式查看，而不让 Renderer 直接获得文件系统能力。
首版解决“结果已落盘但只能复制/再次调用工具才能查看”的断点，不建立通用
Artifact 平台。

## Current evidence

- `lion_code/tooling/result_store.py::ResultStore.process` 已在大结果超过阈值时把
  完整 UTF-8 文本写入本地文件，并在 `ToolResult.details` 中保留
  `persisted_path`、`original_bytes` 和 `result_policy`。
- `lion_code/core/messages.py::ToolResultMessage` 与 Core 工具事件已经携带结构化
  `details`，但 `lion_code/server/app.py::get_messages` 当前只投影结果文本和错误状态。
- `desktop/src/renderer/src/components/ToolActivity.tsx` 当前只有复制动作；
  `WorkPanel.tsx` 的“文件”视图仍是空占位。

## Requirements

### R1. 资源引用投影

为工具调用增加可选的、最小化的 openable resource 引用：

- `ResultStore` 产生的 `details.persisted_path`；
- 已知文件工具的 `file_path` 参数（首版仅覆盖明确的读写/编辑文件工具，不能
  从任意 shell command、搜索摘要或未经约束的字段猜路径）。

REST 历史和当前 WebSocket 工具完成事件都要提供同一语义的可选引用；旧消息没有
引用时必须继续按原契约显示。

### R2. 后端受限读取

新增 capability-protected 的只读读取接口。每次打开都重新解析路径、检查根目录、
检查普通文件属性、检查大小并读取；允许当前工作区和 Lion 默认工具结果目录，
拒绝其余路径、目录、缺失文件和符号链接越界。读取设置严格的字节上限，非 UTF-8
或疑似二进制内容不得进入 Renderer。

返回结构化状态（ready、missing、outside-workspace、not-file、too-large、binary、
encoding-error、changed 或 unreadable），使 UI 能显示明确原因而不是空白或把异常
当成成功内容。读取前后属性不一致时返回 changed；客户端刷新已打开资源时带上上次
属性用于发现替换/竞态。

### R3. 桌面工作面板

- 工具活动在有结果且存在 openable 引用时显示“在工作面板打开”。
- 点击后切换/显示 WorkPanel 的“文件”视图；只读展示文件名、路径、大小、修改时间
  和文本内容。Markdown、普通文本和 unified diff 使用现有展示能力或等价的已有样式。
- loading、过大、二进制、编码失败、缺失、越界和 changed 都要有可理解的状态文案；
  不显示未验证的内容。
- WorkPanel 提供重新加载当前资源的入口；会话切换、历史替换和资源请求失效时，
  不能让旧请求覆盖当前资源。

### R4. 边界与兼容性

- Renderer 不直接 import `fs`、Node 或 raw IPC；所有读取经过已有带 capability 的
  REST 入口。
- 不改变 `ToolRuntime.execute()`、Sanitizer、Egress、ResultStore 的既有执行/脱敏/
  官方结果语义；openable 是结果的 UI 投影。
- 新字段保持可选；严格 REST/WebSocket 解码只接受定义过的 openable 形状，非法响应
  fail closed。

## Out of scope

- 编辑、删除、上传、下载、拖放、跨会话收藏或资源数据库；
- 新增 Artifact Manager/Registry/Resolver、通用 preview plugin 或第二套持久化；
- 二进制、PDF、DOCX 的 Renderer 内联预览；
- 把每个工具结果自动注册为资源，或把 shell 命令中的任意路径暴露为可读资源；
- 系统级“打开方式”以及需要新增 Electron 主进程文件权限的能力。

## Acceptance Criteria

- [x] 超过 `ResultStore` 阈值的成功工具结果在实时流和重启后的 REST 历史中都显示
      打开动作，并能在文件视图读取完整内容或得到有界状态。
- [x] 受支持文件工具的工作区内文件可打开；工作区外、目录、缺失、越界符号链接、
      超过上限、二进制和非 UTF-8 输入均显示对应状态且不返回内容。
- [x] 资源读取前后发生替换/删除或请求乱序时，界面显示 changed/missing 或保留当前
      资源，不显示过期请求的内容。
- [x] 既有历史、工具运行、脱敏、Egress、Git 工作台和消息流行为不回归；旧消息和
      没有 openable 字段的事件仍能严格解码。
- [x] 增加后端资源边界/状态测试和桌面协议、REST、运行时/工作面板测试；通过受影响
      的 targeted checks、`git diff --check`，不以全量测试替代范围验证。

## Decisions

- 采用提案的 P0 最小切片：投影 ResultStore 现有落盘能力，不复制 Maka 的 Artifact
  身份、数据库或生命周期模型。
- 资源状态由 Python REST 读取接口决定，Renderer 只保存当前展示状态和请求代数；
  工具展示组件只接收资源数据和打开回调。
- 读取上限和允许根目录作为单一后端函数的安全边界集中测试，避免在 UI 复制文件
  读取逻辑。

## Risks / deferred

- ResultStore 默认目录不是 session-scoped；首版仅允许固定的 Lion tool-results 根目录，
  不把它扩展成跨会话资源索引。
- 文件在两次检查之间改变仍可能产生竞态；读取前后 stat 校验和 changed 状态把它
  收敛为显式失败，不承诺快照一致性。
- 只读 UTF-8 文本不覆盖二进制预览；如后续需要系统打开或附件生命周期，应另立提案。
