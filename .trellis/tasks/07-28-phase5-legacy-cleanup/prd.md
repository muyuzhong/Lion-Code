# 阶段 5：移除 legacy 路径与 SDK 依赖

> 上游依据：`docs/tui-migration-audit.md` §12 阶段 5。阶段 4 已完成双协议
> Core Runtime、新 TUI、Provider side-query、溢出恢复与真机流式验收。

## Goal

让 Core Runtime、Provider、JSONL 会话和新 TUI 成为唯一运行路径，删除已经失去
运行价值的 SDK 对话、手工压缩、旧 TUI 与旧会话写入实现，同时继续支持读取并迁移
历史 `.json` 会话。

## Requirements

### A. Core Runtime 成为唯一主路径

1. `Agent` 不再通过 `LION_CORE_RUNTIME` 或可选布尔值选择新旧运行时；OpenAI-compatible
   和 Anthropic 均直接构造 Provider 与 `LionAgentRuntime`。
2. `configure_api()`、子 Agent 配置和 `api_configured` 只依赖 Lion 自己保存的 Provider
   配置，不再先构造或反向读取 OpenAI/Anthropic SDK client。
3. goal、loop、plan、learning、dream、side-query 等现有能力继续使用 Core canonical
   message/history 与 Provider 服务，不保留协议私有 message 列表作为第二状态源。
4. Provider/模型热切换只允许在会话空闲时执行；切换必须保留 canonical history，并原子刷新
   compactor、文本查询和模型限制等 Provider 派生服务。新 Provider 构造失败时保持原状态，旧
   Provider 不得在活跃流中被关闭。

### B. 删除 legacy 对话、压缩和查询实现

1. 删除 `_chat_openai`、`_chat_anthropic`、`_call_*_stream`、`_compact_*` 及旧手工压缩
   pipeline；保留 Core context manager、Provider compactor 和阶段 4 的 overflow 自动恢复。
2. 删除 `LegacySdkTextQueryService` 及其导出和专用测试，所有文本查询复用
   `ProviderTextQueryService`。
3. `lion_code/` 中不再导入或调用 `openai`、`anthropic` SDK，`pyproject.toml` 移除这两个
   直接依赖；仓库若存在依赖锁文件则同步更新（当前仓库没有锁文件）。

### C. 删除旧 TUI 与全局 sink 桥

1. 删除 `legacy_tui.py`、`--legacy-tui` 命令行入口和回退分支；裸启动与显式 TUI 路径
   均进入当前 Textual 应用。
2. 删除 `ui.set_sink` 全局桥。逐项审计当前新 TUI 接收的 status、retry、error、subagent
   信息：已有结构化事件覆盖的直接复用；确有缺口的以最小 typed application event 或
   session callback 补齐，不得静默丢失当前用户可见反馈。
3. REPL 如仍需要 `ui.print_*`，只保留直接 stdout 渲染，不再存在跨前端全局可变 sink。

### D. 收敛会话持久化

1. 删除 `lion_code/session.py` 旧 JSON 写入器以及 Agent 中对应的旧写入/恢复分支；运行中
   的保存和恢复只使用 `SessionRecorder` / `JsonlSessionStorage`。
2. 保留 `session_runtime/legacy.py` 的旧 `.json` 发现、读取和迁移能力，迁移不得删除或
   覆盖用户的源文件。

### E. 文档和交付

1. 更新 `UPSTREAM.md`、迁移审计、TUI/CLI 文档及帮助文本，使其只描述真实存在的路径。
2. 每个可验证切片使用中文提交并直接推送 `master`，不创建 PR。

## Out of Scope

- 删除用户磁盘上已有的旧 `.json` 会话文件。
- 新 Provider catalog、OAuth 或模型配置体系。
- 重新设计 JSONL 格式、新 TUI 布局或 overflow 恢复协议。
- 与 legacy 删除无关的 Agent 大规模模块化重构。

## Acceptance Criteria

- [ ] `lion_code/` 中 `import openai` / `import anthropic` 为零，项目依赖和锁文件中不再有
      两个 SDK 的直接依赖。
- [ ] 产品代码中不存在 `LION_CORE_RUNTIME` 分支、`_chat_*`、`_call_*_stream`、旧压缩
      pipeline、`LegacySdkTextQueryService`、`legacy_tui`、`--legacy-tui` 或 `ui.set_sink`。
- [ ] OpenAI-compatible 与 Anthropic 的 Core/Provider 自动化矩阵通过；阶段 4 的
      overflow → compaction → auto-retry 顺序契约继续通过。
- [ ] 空闲态跨协议/凭证热切换保留 canonical history，并刷新所有 Provider 派生服务；运行中
      切换被明确拒绝且不改变现有 Provider，旧 Provider 不会在活跃流中关闭。
- [ ] 新 TUI 流式增量渲染、工具状态、错误、重试和子 Agent 可见反馈无回归，正常 delta
      不触发 transcript 全量重绘。
- [ ] 新会话只写 JSONL；旧 `.json` 会话仍可发现、读取和迁移，且源文件保持不变。
- [ ] `agent.py` 删除 legacy 后显著缩减，验收时不超过 2500 行；不为达成行数引入无关
      搬迁或新的包装层。
- [ ] 全量 `pytest`、`compileall`、项目已有 lint/type-check 与 `git diff --check` 通过。
- [ ] `UPSTREAM.md` 和相关用户文档同步，Trellis check 与 journal 完成。

## Notes

- 本阶段保持一个任务：各删除项共享 Agent/Core/TUI/session 边界并有严格先后顺序，拆成
  并行子任务会让中间提交出现不可运行组合。
- ponytail full：优先删除和复用已有 Core/Provider/structured-event 能力，不为 legacy
  兼容再建新的抽象层。
