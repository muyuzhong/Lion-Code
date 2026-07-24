# Lion Code TUI 设计方案与开发清单

## 设计原则：TUI 与 Agent 核心完全分离

Agent 核心（`agent.py`）对 TUI 零感知。分离依靠三条已有/新增的边界，核心代码不需要 import 任何 TUI 模块：

```
用户输入 ──► LionTUI ──► agent.chat(text)                （调用边界：公开方法）
Agent 输出 ──► ui.print_* ──► set_sink ──► AgentEvent ──► Textual 消息泵 （输出边界：事件汇）
交互请求 ──► set_confirm_fn / set_plan_approval_fn ──► 模态弹窗        （交互边界：回调注入）
```

1. **输出边界（事件汇）**：`ui.py` 是 Agent 核心唯一的输出口（核心不直接写 stdout）。
   `ui.set_sink(fn)` 注册后，Agent 运行时输出与 spinner 改为发射结构化事件
   `(kind, payload)`，不再写终端；welcome、用户输入提示和 CLI Plan 选项属于
   REPL 自身界面，不进入事件汇。未注册时 REPL 行为完全不变。
2. **调用边界**：TUI 只调用 Agent 的公开方法（`chat / clear_history /
   toggle_plan_mode / show_cost / compact / restore_session / abort / close`），
   与 REPL 使用的是同一组。
3. **交互边界**：危险确认、Plan 审批本就是注入式回调，TUI 换成模态弹窗即可。

Agent 运行时事件种类：`text`（流式增量）、`tool_call`、
`tool_result`、`info`、`error`、`retry`、`confirmation`、`cost`、`spinner`、
`divider`、`sub_agent_start/end`；TUI 侧另加内部事件 `chat_done`。

## 启动与凭证

- `lion-code` 裸启动 = TUI；`--repl` 回到旧 REPL；one-shot prompt 不变。
- TUI 不做启动前 API 检查：无凭证可进界面，首条消息会提示，用 `/model`
  （或 `ctrl+m`）在模态框里配置 provider/model/key/base url，保存即生效
  （`Agent.configure_api` 运行时换客户端，无需重启）并持久化到
  `~/.lion-code/config.json`。
- 凭证三级回退：CLI 参数 > 环境变量 > `/model` 保存的配置。one-shot 与
  REPL 仍需预先配置（硬检查保留）。
- Agent 侧支撑：无凭证时客户端为 `None`（`api_configured`），`chat()` 短路
  报错事件；跨协议切换时目标后端历史清空，同协议换 key/换模型保留历史。

## 配置系统（种子）

`~/.lion-code/tui.json`，缺失/损坏时静默回退默认：

```json
{
  "theme": "textual-dark",
  "keys": {
    "quit": "ctrl+q",
    "abort": "escape",
    "toggle_sidebar": "ctrl+b",
    "new_session": "ctrl+n",
    "model": "ctrl+m"
  }
}
```

主题取 Textual 内置主题名；键位在 App 初始化时经 `BindingsMap.bind` 动态绑定。
新增动作的约定：动作方法 `action_<name>` + 配置 `keys.<name>`，无需改绑定代码。

## 文件

| 文件 | 作用 |
|---|---|
| `lion_code/ui.py` | 输出边界 + `set_sink`（改） |
| `lion_code/tui.py` | TUI 全部实现（新，单文件） |
| `lion_code/config.py` | `/model` 凭证持久化（新） |
| `lion_code/agent.py` | 无凭证构建 + `configure_api` 运行时配置（改） |
| `lion_code/__main__.py` | 默认 TUI / `--repl` / 凭证三级回退（改） |
| `tests/test_tui.py` | sink 单测 + Pilot 冒烟 + 配置流（新） |

## 开发清单

### v1 已交付（最小可观测）
- [x] 流式对话记录（text 事件增量渲染，工具调用/结果/子 Agent 分块显示）
- [x] 会话侧边栏（当前项目会话按时间排序，点击恢复，`＋ New session`）
- [x] 危险确认弹窗（y/n/Esc，接通 `set_confirm_fn`）
- [x] Plan 审批弹窗（1-4 与 REPL 选项一致）
- [x] 快捷键与主题配置（`tui.json`，五个动作 + 内置主题名）
- [x] 状态栏（spinner / token 用量 / 成本）
- [x] 裸启动即 TUI、无凭证可进界面、`/model` 模态配置并持久化
- [x] Esc 中断（`agent.abort()`）

### v2（交互补全）
- [ ] 输入自动补全：`/` 命令与 skill 名（Textual `AutoComplete` 或候选浮层）
- [ ] 权限模式切换（运行时，复用 ModalScreen）
- [ ] `/model` 常用模型候选列表（Select 预选 + 自定义输入）
- [ ] 多行输入（TextArea，Enter 发送 / Shift+Enter 换行，键位可配）
- [ ] 会话历史回放（恢复会话时把消息渲染进聊天区，需 session 消息提取）
- [ ] 工具结果折叠/展开、diff 着色（复用 ui.py 的 diff 分行逻辑下沉为共享函数）
- [ ] Markdown 流式渲染（Textual `Markdown` + 增量 append）
- [ ] 其余 REPL 命令映射（`/dream /learn /goal /loop /memory /skills`）

### v3（配置完善）
- [ ] 自定义主题（tui.json 内嵌颜色表 → 注册 Textual Theme 对象）
- [ ] 键位冲突检测与 `/keys` 查看命令
- [ ] 配置热重载（watch tui.json）
- [ ] 每动作多键位（`"abort": ["escape", "ctrl+c"]`）
