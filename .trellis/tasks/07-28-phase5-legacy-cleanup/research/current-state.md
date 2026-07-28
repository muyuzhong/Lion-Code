# 阶段 5 当前状态调研

## 结论

阶段 4 已经让双协议 Provider/Core、新 TUI、Provider side-query 和 overflow 自动恢复
具备替代能力，但 legacy 代码仍与 `Agent` 初始化、配置、会话历史和 UI 状态反馈交织。
本阶段不能只删除文件，必须先把剩余消费者收敛到已有 canonical 路径，再删除旧实现。

## 运行时与 SDK

- `lion_code/agent.py` 约 3200 行，仍在模块顶层导入 `anthropic` 和 `openai`。
- `Agent.__init__` 仍根据 `LION_CORE_RUNTIME` 决定是否构造 Core，并同时维护
  `_anthropic_messages`、`_openai_messages` 与两个 SDK client。
- `chat()` 仍可分流到 `_chat_openai` / `_chat_anthropic`；文件后部保留
  `_call_*_stream`、协议专用压缩及旧手工压缩 pipeline。
- `configure_api()` 先重建 SDK client，再重建 Provider/Core；子 Agent 参数也会从 SDK
  client 反向读取。阶段 5 应由 Agent 自己保存的 Provider 配置成为唯一来源。
- goal、loop、plan、learning、dream 和部分测试仍直接使用协议私有 messages，需要迁到
  Core canonical history，不能直接删字段。

## 文本查询

- `memory_runtime/query.py` 同时存在 `ProviderTextQueryService` 与
  `LegacySdkTextQueryService`。
- `_build_core_memory_query_service()` 和 `_build_side_query()` 仍保留 SDK fallback；阶段 4
  的 Core/Provider 路径已经覆盖双协议，可删除 fallback、导出和专用测试。

## TUI 与 UI sink

- `legacy_tui.py` 仍由 `__main__.py --legacy-tui` 引用，可连同参数和回退分支删除。
- 当前新 TUI 在 mount/unmount 时仍注册 `ui.set_sink`，接收 subagent、info、error、retry、
  status；`TerminalRenderer` 和测试也依赖该全局桥。
- 因此不能直接删除 sink 后丢弃事件。实施时需逐类确认是否已有 Core/application 结构化
  事件覆盖；只对真实缺口增加最小 typed 事件或 session callback，REPL 继续直接 stdout。
- 阶段 4 的 streaming transcript 已有独立规范，任何 sink 清理都必须保持增量 widget
  身份和禁止 delta 全量重绘的契约。

## 会话

- `SessionRecorder` / `JsonlSessionStorage` 是当前写入路径。
- `session_runtime/legacy.py` 是旧 `.json` 的只读发现与迁移路径，必须保留；已有测试验证
  迁移兼容。
- `lion_code/session.py` 仍包含旧 JSON writer，Agent 也保留旧 serialize/restore 分支，均可
  在 JSONL-only 接线完成后删除。

## 依赖、测试和文档

- `pyproject.toml` 仍声明 `anthropic>=0.40.0`、`openai>=1.50.0`。
- `tests/test_agent_run.py` 大量覆盖 legacy `_call_*_stream`，应删除或以 Core 行为测试替换。
- `tests/test_legacy_tui.py` 同时覆盖旧 TUI 和 sink；应删除旧 TUI 用例并把仍有价值的状态
  可见性断言迁到 application/TUI 测试。
- `tests/test_learning.py`、`tests/test_dream.py` 等直接操作协议私有 messages，需要改用
  canonical state。
- `UPSTREAM.md` 与 `docs/tui-migration-audit.md` 必须在完成后记录删除边界和保留的旧会话
  只读迁移。

## 关键风险

1. 先删 SDK 字段会破坏 child agent、API 热切换或目标/学习路径。
2. 把只读旧会话迁移误当成旧写入一起删除，会让已有用户无法恢复历史。
3. 直接移除 `ui.set_sink` 会让新 TUI 的非流式状态反馈静默消失。
4. legacy 测试直接删除而不补 Core 等价断言，会造成表面绿、覆盖面下降。
