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
