# Agent Note: 删除 tui/widgets.py 从未实例化的侧边栏子系统与 tests-only 的 render_chat_item 家族

- Status: proposed
- 日期: 2026-08-18
- 范围: `lion_code/tui/widgets.py`、`lion_code/tui/__init__.py`、`lion_code/application/session_stats.py`、`tests/tui/test_tui_themes.py`

## Problem

`tui/widgets.py`（2260 行，仓库最大文件）里有两块从未被产品路径触达的表面：

1. **侧边栏子系统**：`SessionSidebar`（:101）、`CompactSessionInfo`（:131）、
   `render_session_sidebar`（:1485）、`render_compact_session_info`（:1576）、
   `SessionSummarySource` 协议（:55）、`_session_summary_fingerprint`（:150）——
   `rg` 全仓引用只有 `widgets.py` 自身与 `tui/__init__.py:29-37,43-66` 的
   re-export；`tui/app.py`（唯一产品入口）零引用。整条私有 helper 链只服务该家族，
   每个 helper 的调用点都已核对（`_context_usage`:1589、`_styled_cwd`:1582、
   `_compact_token_count`:1509/2001、`_context_file_labels`/`_context_file_label`:
   1529/2031、`_thinking_level`:1587、`_git_branch`:2014、`_compact_usage_count`:
   1499-1500、`_format_cost`:1505、`_plural`:1494-1495、`_limited_bullet_list`/
   `_bullet_list`:1513/1528/2225、`_short_path`:2006/2045、`_comma_list`:
   1512/1518/1523、`_LineLimitedCommaList`:2194）。随行的
   `application/session_stats.py::SessionStats` 唯一消费者就是侧边栏（
   `widgets.py:35,165,1492`）。
2. **`render_chat_item` 家族**：`render_chat_item`（:1598）只在
   `tests/tui/test_tui_themes.py:362,369` 被调用；其专属渲染链
   （`_chat_item_role_style`/`_tool_accent_style`/`_render_tool_chat_body`/
   `_render_tool_invocation`/`_split_tool_invocation`/`_visible_chat_text`/
   `_render_chat_body`/`_render_patch_body`，:1642-1802，以及只服务它的
   Markdown 渲染家族 `ThemedMarkdown`/`LeftAlignedMarkdownHeading`/
   `ThemedCodeBlock`/`_markdown_theme`/`_render_fenced_body` 等，:1804-1997）
   与活跃的 `TranscriptView` 路径（:590+ 的 `_transcript_*` 家族）不共享。

## Proposal

1. 删除侧边栏家族（含 `SessionSummarySource` 协议、`SessionStats` 类型与
   `tui/__init__.py` 对应导出）及上述私有 helper 链。
2. 删除 `render_chat_item` 家族与 tests-only 用例（`test_tui_themes.py:362,369`）；
   实施时对每个待删符号先 `rg` 核对调用者（尤其确认 Markdown 渲染家族与
   `StreamingTranscriptMessageWidget`/`TranscriptView` 无共享），删完跑 TUI 测试。
3. 若删除后 `tui/__init__.py` 中对应 `__all__` 收缩，同步 `tests/architecture/`
   若有精确表面断言。

## Why not keep it

TUI 的前端渲染已全部收敛到 `TranscriptView` 补全建议等活跃组件；侧边栏是 Tau
迁移期带入但从未接线的子系统（`SessionSummarySource` 需要 `session.context_window_tokens`
等协议字段，产品侧 `LionCodingSession` 从未实现该投影——这正是它从未被实例化的
原因）。`render_chat_item` 是被 TUI 新渲染路径取代后的旧转录渲染器，只剩测试钉住。
两部分合计约 600 行（含私有 helper），删除后 widgets.py 收缩约四分之一，且
`app.py` 活跃路径零改动。

## Acceptance criteria

- `rg -n "SessionSidebar|CompactSessionInfo|render_session_sidebar|render_compact_session_info|SessionSummarySource|SessionStats|render_chat_item" lion_code tests` 零命中。
- `tui/app.py` 的 `TranscriptView`/`render_completion_suggestions` 活跃路径不变：
  `tests/tui/test_tui_app.py`、`test_tui_autocomplete.py`、`test_tui_adapter.py`
  全绿；全量可跑 unittest 通过。

## Risks

- 侧边栏若列入未来 TUI 排版计划（侧边信息展示），删除后重建成本与该子系统尺寸
  对称；当前无任何文档/任务提及此规划（`.trellis/tasks/` 无侧边栏相关条目）。
- 私有 helper 中 `_format_cost`/`_compact_usage_count` 等命名与 usage 展示语义
  相近，删除前确认无活跃组件复用（已核对：无）。

## 落地

- 提交: `1cbe9cd`
- PR: #50（标题：refactor: 删除 TUI 侧边栏子系统与 tests-only 的 render_chat_item 家族）
- 门禁证据: 定向测试全绿（排除 5 个已知环境性/既有失败：test_coding_session_ports、test_composition_profiles::test_all_profiles_return_meta_facade、test_capability_migration::test_session_participant、test_agent_core_runtime::test_plan_clear、test_cli::test_repl_routes_generic_command）；CI Quality gates 待绿。
