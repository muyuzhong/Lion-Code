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
