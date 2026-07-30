# 阶段 5 当前状态

> 复核时间：2026-07-30。依赖与文档收尾、最终 Trellis check 及远端同步均已完成；
> 用户已确认验收，本次收尾将任务归档。

## 结论

阶段 5 的四个运行时删除切片已经落地，Core Runtime、Provider、canonical history、
JSONL Session 与 Textual TUI 已成为产品唯一运行路径。切片 5 已移除主运行时的 SDK
依赖并同步用户文档；没有为兼容旧路径增加新 adapter、no-op 或第二状态源。

## 已落地切片

| 切片 | 提交 | 当前结果 |
|---|---|---|
| Core/Provider 单路径 | `64e25b6` | 双协议、子 Agent、side-query 与热切换统一到 Core |
| SDK 对话/查询/压缩删除 | `9e92d09` | legacy chat、手工压缩、协议私有 history 与 SDK query 删除 |
| JSONL-only Session | `1f95fb0` | 旧 writer 删除；旧 `.json` 只读发现/迁移保留 |
| TUI/sink 删除 | `3370351` | Textual TUI 唯一；REPL 直写 stdout；会话 notice 补足非流式反馈 |
| 依赖/文档收尾 | `46f9dfe` | 主 dependencies 移除 SDK；用户文档、规范与迁移审计已同步 |

## 当前运行边界

- `Agent` 始终持有 `LionAgentRuntime`，消息唯一状态是 Core canonical history。
- OpenAI-compatible 与 Anthropic 均由 `lion_code/providers/` 内置 HTTP Provider 实现；
  `lion_code/` 不导入第三方 `openai` / `anthropic` 包。
- Provider/模型切换仅允许在空闲态执行，保留 history 并刷新 compactor、文本查询与模型
  限制；活动流中拒绝切换。
- TUI 只消费 Core/application typed events 与会话级 notice/确认回调；正常 delta 增量追加，
  工具行原位更新。REPL 使用 `ui.print_*` 直接输出，不存在全局 sink。
- 新会话只写 `~/.lion-code/sessions/*.jsonl`。旧 `.json` 只用于读取和迁移；生成 JSONL
  后源文件保持不变。
- `lion_code/agent.py` 当前实测为 2116 行，低于 2500 行验收上限。

## 残留扫描分类

### 产品代码必须为零

以下模式在 `lion_code/` 中扫描为零：第三方 SDK import、`LION_CORE_RUNTIME`、legacy chat/
stream/compaction、`LegacySdkTextQueryService`、旧 TUI 入口、全局 UI sink。协议模块名
`providers/openai_compatible.py`、`providers/anthropic.py` 是当前内置 Provider，不属于残留。

### 有意保留

- `session_runtime/legacy.py` 中 `_openai_messages` / `_anthropic_messages` 只解析用户已有的旧
  `.json`，不参与新会话写入或模型调用。
- `tests/` 中对已删除符号的否定断言与 CLI 拒绝测试用于防回归。
- `docs/tui-migration-audit.md`、Trellis PRD/design/implement 与历史 journal 中的旧符号用于
  记录迁移决策，不是可执行路径。
- 在线 context benchmark 是独立研究工具；若保留 OpenAI SDK，只能放在惰性导入的
  benchmark optional extra，基础安装、离线评测和产品运行不能依赖它。

### 最终检查结论

- 根线程全量 pytest：473 passed、6 skipped、6 subtests passed；独立关键矩阵：183 passed。
- compileall、CLI help、TOML/JSON 解析、产品禁止符号扫描、阶段范围 Ruff F 与
  `git diff --check` 通过。
- 仓库没有项目级 mypy 配置；临时运行 mypy 的 97 条诊断属于既有未配置基线，不为本阶段
  扩张重构。用户已于 2026-07-30 确认验收。

## 本切片验证

- 双协议/provider/application/session/TUI/CLI 矩阵：277 passed、1 skipped。
- 全量回归：473 passed、6 skipped、6 subtests passed。
- `python -m compileall -q lion_code tests`：通过。
- `python -m ruff check lion_code tests benchmarks --select F`：通过。
- `python -m lion_code --help`：通过；帮助中不存在旧 TUI 参数。
- 主依赖 TOML 解析：仅 pydantic、rich、textual、pygments、anyio、httpx。
- 产品禁止符号扫描：零命中。
