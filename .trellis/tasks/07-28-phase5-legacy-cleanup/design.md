# 阶段 5 技术设计

## 设计目标

删除兼容层后，运行数据只沿一条链路流动：

```text
CLI / TUI
  → LionCodingSession
  → Agent + LionAgentRuntime
  → Provider
  → canonical Core messages
  → SessionRecorder / JSONL
```

旧 `.json` 只在恢复入口由 `session_runtime/legacy.py` 读取并迁移，不参与新写入。

## 决策 1：Core 与 Provider 必选

- 移除 `_use_core_runtime` 和 `LION_CORE_RUNTIME` 条件分支。
- `Agent` 始终由 protocol、model、API key/base URL 构造对应 Provider，再构造
  `LionAgentRuntime`；Core runtime 类型不再是 optional。
- Agent 保存构造 Provider 所需的最小配置，`configure_api()` 和 child agent 复用这些值。
  不从第三方 SDK client 的私有或半公开属性反向推导配置。
- `api_configured` 以当前 Provider 所需凭据和配置是否齐全为准。

## 决策 2：canonical history 是唯一消息状态

- 删除 `_openai_messages` / `_anthropic_messages` 及双写逻辑。
- goal、loop、plan、learning、dream 需要上下文时，从现有 Core context/session projection
  读取，不新建“简化历史”副本。
- chat、continuation、compaction 和 overflow retry 只调用 `LionAgentRuntime` 已有接口。
- 旧协议专用流解析和压缩代码在消费者归零后整块删除。

## 决策 3：查询统一走 Provider 服务

- memory、evaluator、classifier、dream 的纯文本查询复用
  `ProviderTextQueryService`/已有 side-query 构造器。
- 删除 `LegacySdkTextQueryService`，不增加另一层兼容 adapter。
- query 调用错误继续遵循现有 Provider/Core 错误模型，不重新解释为 SDK 异常。

## 决策 4：新 TUI 不依赖全局 UI sink

删除 sink 前对现有事件种类建立映射：

| sink 种类 | 目标处理 |
|---|---|
| retry | 复用 Core/application 的 retry 事件 |
| error | 复用 canonical error / session terminal event |
| subagent start/end | 复用 tool/application 事件；若缺失，仅补最小 typed 事件 |
| info/status | 命令结果使用 session notice；运行时必要状态使用最小 typed 事件 |

`LionCodingSession`/TUI 只消费 typed event 或明确的 session callback，不再安装进程级
可变 sink。REPL 的 `ui.print_*` 直接输出到终端。此改动不触碰 transcript delta 的
`MarkdownStream.write()` 路径。

## 决策 5：会话写入 JSONL-only，迁移 read-only

- 新建、追加、压缩记录和 restore 后继续写入均由 SessionRecorder/JSONL storage 负责。
- 删除旧 JSON writer 和 Agent 中仅为旧 writer 服务的 serialize/auto-save 分支。
- 保留 legacy reader/list/migrate；迁移输出到 JSONL，旧源文件不改名、不覆盖、不删除。

## 删除顺序与不变量

1. 先让 Core/Provider 配置和 canonical history 覆盖所有消费者。
2. 再删除 SDK query、legacy chat/compaction 和协议私有状态。
3. 独立收敛 session write/read 边界。
4. 审计并替代 UI sink 后删除旧 TUI 和 bridge。
5. 最后移除依赖、更新文档并做残留扫描。

每个中间提交都必须可运行。任何删除都需用“符号残留扫描 + 目标测试”证明消费者已经
归零；不通过空实现、永久 no-op 或捕获所有异常来制造兼容。

## 兼容与错误边界

- 保持 OpenAI-compatible/Anthropic Provider 行为和 API 热切换能力。
- 保持阶段 4 overflow 只对 canonical context overflow 触发且最多自动重试一次。
- 保持旧会话读取；不承诺继续生成旧 JSON。
- 保持 TUI terminal error/abort 最多一次全量 reconcile，正常流式 delta 不全量重绘。

## 验证策略

- 切片级：对应 agent/provider、memory query、session migration、application/TUI 目标测试。
- 架构级：扫描禁止符号、依赖树和 CLI help；验证两协议都只进入 Core。
- 回归级：全量 pytest、compileall、lint/type-check、`git diff --check`。
- 规模级：记录 `agent.py` 最终行数，目标不超过 2500 行，但不通过无关搬迁达标。
