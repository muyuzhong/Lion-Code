# D 组设计：Windows 文件拖拽与补全渲染行裁剪

## 当前状态

- `tui/file_drop.py` 先尝试完整路径，再固定使用 `shlex.split(..., posix=True)`。
  单个裸 Windows 路径通常可用，但带引号或多路径输入会丢失盘符后的反斜杠；
  `file:///C:/...` 也没有转换为 Windows 本地路径。现有测试因此整文件跳过 Windows。
- `LionTuiApp._visible_completion_state()` 只按条目数裁剪。分类标题、分类间空行与
  长 description 换行都不计入预算，建议框可能超过 CSS 的可见高度。
- Tau 当前版本已经提供按实际渲染行测量的补全裁剪函数；文件拖拽实现则仍与 Lion
  相同，没有可直接同步的 Windows 修复。

## D9：Windows 拖拽路径归一化

1. 保留完整路径快速路径和现有 POSIX `shlex` 解析，避免改变单文件与 POSIX 终端行为。
2. POSIX token 不能全部解析为现存绝对路径时，再用 `shlex` 非 POSIX 模式重试，
   仅剥离成对的外层单双引号，保留盘符和反斜杠。
3. `file://` 路径通过标准库 `url2pathname()` 转为当前平台路径。
4. 输出只为含空白路径补双引号，不重写 Windows 路径分隔符；任一 token 非现存
   绝对路径时仍返回 `None`，不把普通粘贴误判成拖拽。

## D10：补全窗口按渲染行裁剪

1. 以 Tau 的 `_visible_completion_state()` 为窗口算法基础，并按完整 Rich 表格的实际
   输出测量分类标题、分类间隔、条目本身和 description 换行；不能逐项测量，因为整表
   最长命令会改变 description 列宽，且保留分类的单项渲染会重复计算标题。
2. `LionTuiApp._refresh_completions()` 继续使用既有 16 行上限，只把窗口单位从
   item 改为 rendered line，并传入当前建议框宽度。
3. 不迁入 Tau 更大的动态终端高度预算和响应式布局状态；当前 CSS `max-height: 17`
   已提供稳定容器边界，本子项只修复 PRD 指定的 `_visible_completion_state` 语义。

## 兼容与验证

- Windows、POSIX、URI、引号、多路径和普通文本粘贴均有回归测试。
- 补全测试断言选中项可见、总渲染行不超预算、长 description 换行被计数。
- D9、D10 分别提交并直接推送；完成后运行 TUI 目标测试与全量测试。

## E11：流式 transcript 无闪烁

### 根因

`LionTuiApp._run_prompt()` 在每个会话事件后调用 `TranscriptView.update_from_state()`；
该方法进入 `_redraw()`，会卸载并重新挂载窗口内的全部消息。provider 高频 text delta
因此反复重建 Markdown widget 和布局，造成屏幕闪烁。与此同时，Lion 已从 Tau vendor
了 `append_assistant_delta()`、`append_thinking_delta()`、`finish_assistant_message()`、
`append_item()` 与 `update_item()`，只是应用层尚未接线。

### 方案

1. 以 Tau 当前 `_apply_streaming_transcript_event()` 为上游依据，在 Lion 应用层按
   `MessageUpdate`、`MessageEnd`、`ToolExecution*` 与 retry 边界调用现有增量 API。
2. text/thinking delta 只向活动 `StreamingTranscriptMessageWidget` 追加 fragment；普通
   assistant 消息在 `MessageEnd` 绑定 canonical `ChatItem`，结构化 thinking/text 消息
   仅替换本轮临时尾部。
3. 工具开始时追加一个工具行，工具进度和结果原位更新；状态栏仍可刷新，但不触碰
   transcript 历史 DOM。异常终止允许一次全量同步，保证错误项不丢失。
4. 不新增节流器、渲染队列或第二套状态；复用 adapter 的唯一投影和已 vendor 的 Tau
   widget API。

### 回归判据

- 两个连续 text delta 必须分别进入 `MarkdownStream.write()`，不得调用整段 Markdown
  replace/update，也不得调用 `TranscriptView.update_from_state()`。
- 最终 assistant 文本与 `TuiState` canonical item 一致，既有历史消息 widget 身份不变。
- thinking、工具开始/进度/结束与异常消息终止覆盖目标测试。
