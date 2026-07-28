# D 组实施计划

1. 在 `tui/file_drop.py` 增加最小的双模式 token 解析和平台 URI 转换，删除测试文件的
   Windows 整体跳过，补齐 Windows 路径分隔符、引号与多路径用例。
2. 运行 `tests/tui/test_tui_file_drop.py`，确认非路径粘贴仍回退 Textual 默认处理；
   将 D9 独立提交并推送。
3. 以 Tau 的 `_visible_completion_state` 为基础实现按渲染行裁剪；测量完整 Rich 表格
   输出，避免分类标题重复计费和最长命令挤压 description 列时的低估，再接入
   `LionTuiApp._refresh_completions()`，不引入额外布局抽象。
4. 在 `tests/tui/test_tui_app.py` 增加纯函数回归测试，覆盖分类标题、选中项窗口和
   description 换行；运行 TUI 相关测试后将 D10 独立提交并推送。
5. 运行全量 `pytest`、`compileall`、可用的 lint/type-check 与 `git diff --check`；
   更新相关规范、Trellis journal，并评估阶段 4 是否满足归档条件。

## E11 实施计划

1. 在 `lion_code/tui/app.py` 增加最小的流式 transcript 事件分发函数；`_run_prompt()`
   先由 adapter 更新 `TuiState`，再调用该函数，移除逐事件 `update_from_state()`。
2. 对齐 Tau 已验证的消息收敛规则：普通文本绑定 canonical item，thinking/text 多块消息
   仅替换活动尾部，tool/retry 行使用 `append_item()` 或 `update_item()`。
3. 在 `tests/tui/test_tui_app.py` 增加真实 Textual pilot 回归，跟踪 stream fragment、全量
   redraw 和历史 widget 身份；补齐 thinking/tool/error 边界的最小断言。
4. 更新 TUI 交互规范，运行 TUI 目标测试、全量 pytest、compileall、lint/type-check 与
   `git diff --check`，再以中文提交直接推送 `master`。
