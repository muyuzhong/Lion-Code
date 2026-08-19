# Lion Code TUI 使用说明与运行边界

Lion Code 只有一个 Textual TUI。裸运行 `lion-code` 启动 TUI；`--repl` 启动纯文本
REPL；传入位置参数时执行 one-shot prompt。旧前端和进程级 UI sink 已删除。

## 启动方式

```powershell
lion-code                         # Textual TUI
lion-code --resume                # TUI 启动后恢复最近会话
lion-code --repl                  # 纯文本 REPL
lion-code "检查当前项目"          # one-shot prompt
```

TUI 允许在没有凭证时启动，并自动打开 `/model` 配置表单。one-shot 与 REPL 必须预先
提供凭证。启动配置优先级为：CLI 参数、环境变量、`~/.lion-code/config.json` 中由
`/model` 保存的配置。

- Anthropic：`ANTHROPIC_API_KEY`，可选 `ANTHROPIC_BASE_URL`。
- OpenAI-compatible：`OPENAI_API_KEY` 与 `OPENAI_BASE_URL`，也可用 `--api-base`。
- `--model` 或 `LION_CODE_MODEL` 选择模型。

`openai-compatible` 与 `anthropic` 在这里是 Provider 协议名。运行时直接使用 Lion
内置的 HTTP Provider，不依赖 OpenAI 或 Anthropic Python SDK。

## 唯一运行链路

```text
Textual TUI
  → LionCodingSession
  → Agent + ConversationRuntime
  → OpenAICompatibleProvider / AnthropicProvider
  → canonical Core messages/events
     ├→ TuiEventAdapter / TranscriptView
     └→ SessionRecorder / JSONL
```

TUI 通过 `LionCodingSession` 消费 Core/application 事件。文本与 thinking delta 直接追加到
活动的 Markdown stream，工具状态原位更新；正常流式事件不会重建整个 transcript。错误或
中止允许在终止边界做一次全量校准。

非流式 info/error 通过会话级 notice callback 进入 Textual 消息泵；权限确认和 Plan 审批
继续使用注入式异步回调。TUI 创建会话门面时会关闭 Agent 的终端 renderer，因此不会与
Textual 争用 stdout。REPL 则保留 `ui.print_*` 的直接终端输出。两种前端之间不存在全局
可变 sink。

## TUI 命令

| 命令 | 作用 |
|---|---|
| `/model [name]` | 选择模型；无参数时打开模型/API 配置 |
| `/clear`、`/new` | 清空当前 transcript 并开始新会话 |
| `/resume [session-id]` | 恢复指定会话；无参数时打开会话选择器 |
| `/plan` | 切换 Plan 模式 |
| `/cost` | 显示本会话输入/输出 Token |
| `/compact` | 使用当前 Provider 压缩上下文 |
| `/thinking [level]` | 切换 `off/minimal/low/medium/high/xhigh` 档位 |
| `/theme [name]` | 切换 TUI 主题；无参数时打开选择器 |
| `/quit`、`/exit` | 退出 TUI |

输入框支持命令、Skill、模型、主题和本地路径补全。Agent 运行中按 Enter 会把消息作为
steer 入队，按 Alt+Enter 作为 follow-up 入队；运行中的 slash command 会被拒绝，先按
Esc 中止当前任务。

## 默认快捷键

| 快捷键 | 作用 |
|---|---|
| `Esc` | 关闭补全或中止当前任务 |
| `Ctrl+K` | 打开命令补全 |
| `Ctrl+R` | 打开会话选择器 |
| `Alt+Enter` | 提交 follow-up |
| `Tab` / `↑` / `↓` | 接受或移动补全选择 |
| `Shift+Tab` | 循环 thinking 档位 |
| `Ctrl+P` | 打开模型选择器 |
| `Ctrl+T` | 显示/隐藏 thinking |
| `Ctrl+O` | 展开/折叠工具结果 |
| `Ctrl+B` | 显示/隐藏会话侧栏 |
| `Ctrl+N` | 新建会话 |
| `Ctrl+M` | 打开模型/API 配置 |
| `Ctrl+D` | 退出 TUI |

可配置快捷键、主题和完成通知保存在 `~/.lion-code/tui.json`。当前真正接线的顶层设置为
`theme`、`turn_notification`（`off`、`bell` 或 `desktop`）和 `keybindings`；未知字段会被
忽略，已识别字段仍会严格校验。

## 会话持久化

新会话只写入 `~/.lion-code/sessions/<session-id>.jsonl`。`SessionRecorder` 按 canonical
完成态事件追加消息、模型/thinking 变更和压缩记录。

同目录下旧版本的 `<session-id>.json` 仅用于发现、读取和迁移。首次恢复旧会话时会生成
对应 JSONL，此后继续写 JSONL；原 `.json` 文件不会被覆盖、改名或删除。
