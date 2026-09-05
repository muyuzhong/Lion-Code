# 可打开产物工作台技术方案

## 1. 目标边界

```
ToolResult.details / file tool args
          │  (只投影安全引用)
          ├── REST /api/messages ──┐
          └── WS tool result ──────┤
                                    ▼
                         shared ChatProtocolState
                                    │
                         assistant-ui artifact
                                    │
               ToolActivity ── open callback ──┐
                                                ▼
                              LionRestClient /api/resources/open
                                                │ capability + cwd/root checks
                                                ▼
                                   OpenableResourceResponse
                                                │
                                      LionRuntimeSnapshot
                                                ▼
                                           WorkPanel 文件
```

Python 仍是 canonical session、工具结果和文件读取的所有者；Renderer 只保存当前
资源的加载/展示状态。不会在 `ToolRuntime`、Core history 或 Electron IPC 中加入第二
条执行/持久化路径。

## 2. 后端资源投影与读取

新增一个小型 application 纯函数模块（不引入 Manager/Registry/Resolver）：

- `openable_resource_for_tool(tool_name, args, details)`：只识别
  `details.persisted_path`，以及白名单文件工具的 `file_path`；返回路径和可选的
  `expected_size`，不把整个 details 原样传给桌面。
- `read_openable_resource(cwd, raw_path, expected_size, expected_mtime_ns)`：
  - 把相对路径解析到当前 cwd，把绝对路径限制在 `cwd` 或固定
    `Path.home() / ".lion-code" / "tool-results"` 根内；
  - `resolve(strict=False)` 后再次做根目录相对关系判断，拒绝符号链接越界；
  - `stat` 检查普通文件和读取上限；
  - 若请求携带上次的 size/mtime，属性改变返回 `changed`；
  - 以有界二进制读取 + 严格 UTF-8 decode 读取，检测 NUL/二进制和
    `UnicodeDecodeError`，异常只返回结构化状态；
  - 读取后再次 `stat`，属性变化或文件超限时丢弃内容并返回 changed/too-large。

读取上限选定为一个集中定义的 256 KiB。这个上限只约束 WorkPanel 传输，不改变
ResultStore 的持久化阈值。格式按后缀分类为 text、markdown 或 diff，未知后缀回退
text；错误状态永远不携带内容。

`lion_code/server/models.py` 增加严格 DTO：

- `OpenableResourceRef`：`path`、可选 `expectedSize`；
- `OpenableResourceResponse`：`status`、安全展示所需的 `name/path/format/size/mtime`、
  可空 `content` 和可选诊断文案；
- `ToolCallDTO.openable` 为可空字段。

`lion_code/server/app.py`：

- `/api/messages` 从 `ToolResultMessage.details` 和 assistant tool call 参数生成
  `openable`，只暴露投影后的字段；
- 新增 `GET /api/resources/open`，接收路径和上次属性，沿用既有 API router 的
  capability/local-request 依赖，调用 `read_openable_resource`。验证类结果以
 结构化响应返回，未授权/非法请求仍走现有 HTTP 错误边界。

## 3. REST / WebSocket 合同

### REST

`desktop/src/renderer/src/backend.ts` 增加 `OpenableResourceResponse` 类型、严格
`isOpenableResourceResponse` guard 和 `LionRestClient.openResource`。所有字段和 status
枚举显式验证；不接受未定义的资源结构，也不把服务器的任意 JSON cast 成类型。

`isToolCall` 允许 `openable` 缺省、null 或严格的 ref；旧历史保持兼容。

### WebSocket

`desktop/src/shared/chat.ts`：

- `ToolCallItem` 增加可选 `openable`；
- `AgentToolResult` 增加可选、受约束的 details（仅为计算 openable 所需）；
- `isToolResult` 允许合法 details，其他形状仍 fail closed；
- `tool_execution_end` / update 在既有 tool 状态更新中调用同一前端投影逻辑，优先
  persisted path，回退到白名单 file tool 的 `file_path`；
- `projectLionMessage` 将引用放入 assistant-ui tool-call part 的 UI-only `artifact`，
  不把路径混入可复制的工具结果文本。

REST 与 WS 的 openable 语义保持一致，但旧消息没有该字段仍可显示。

## 4. Runtime 与 UI

`LionAssistantRuntimeAdapter` 增加：

- `openedResource` 快照，状态包含 loading 或后端 response；
- `openResource(ref)` / `reloadOpenedResource()`，递增请求代数；只有当前请求和当前
  session 代数都匹配时才写入快照；
- `loadCanonicalHistory`、session switch/new session、stop/协议失效时清空旧资源。

`ChatThread` 把 `adapter.openResource` 作为 callback 注入 ToolActivity wrapper，保持
展示组件只消费 `artifact` 数据和 callback，不直接依赖 backend/lionRuntime。

`ToolActivity`：

- 在非 error、已有结果且 `artifact` 是合法 openable ref 时显示“在工作面板打开”；
- 点击只调用 callback，不读取文件，不改变工具结果文本。

`WorkPanel`：

- 监听 runtime 的 `openedResource`，有资源时选择“文件”视图；
- loading 显示占位；ready 按 format 用现有 Markdown/pre/diff 展示；
- 非 ready 状态显示状态文案和元数据；提供重新加载；不提供编辑控件。

## 5. 一致性、安全与失败语义

- Renderer 无 `fs`、Node、raw IPC；读取只有一个 capability-protected REST 入口。
- 路径在后端每次 resolve/stat/read，允许根目录是当前 cwd 与固定 tool-results 根；不
  把客户端传入路径视为已授权。
- 不读取或回显错误状态的内容，避免把二进制/乱码/大文件送入 IPC；结果原本经过的
  Sanitizer 和 Egress 链完全不动。
- 文件替换、删除、读取失败返回 typed status；异步请求乱序通过 request generation
  丢弃，不用旧内容覆盖新会话。
- 新字段是 optional，严格协议测试覆盖缺省、合法和 malformed cases。

## 6. 验证策略

- Python：application path/status 单测，server API 的 capability、历史投影和状态
  响应测试；
- TypeScript：chat protocol 解码/投影、REST guard/client、runtime request generation
  和 session reset 测试；
- React：ToolActivity 按钮与 WorkPanel ready/error/read-only 状态测试；
- 运行受影响测试、desktop typecheck/build（若改动触发对应门禁）及 `git diff --check`。
