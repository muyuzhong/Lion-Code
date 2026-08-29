# 工具调用链路与执行管线 (Tool Call Flow)

本文档记录一次工具调用从模型发起、中间件拦截、执行体调用到结果收敛的完整管道链路。

## 工具执行全流程图

```
Model Response (AssistantMessage with ToolCall)
  │
  ├─ 1. Kernel 边界分批 (_tool_call_batches)
  │     └─ 区分 sequential 屏障 与 parallel 批次 (需满足 read_only + concurrency_safe)
  │
  ├─ 2. Adapter 转换 (adapt_lion_tool)
  │     └─ 检查 CancellationView -> 桥接 streaming on_update 回调 -> 调用 ToolRuntime.execute()
  │
  ▼
ToolRuntime.execute()
  │
  ├─ 3. 工具解析: ToolRegistry.resolve(name)
  │     └─ 若未找到，返回 LookupError 错误结果
  │
  ├─ 4. Pre 中间件管道 (按注册顺序逐级进入):
  │     │
  │     ├─ CancellationMiddleware: 检查取消标记，若取消则中断返回
  │     │
  │     ├─ WorkspaceSnapshotMiddleware: 若声明 mutates_workspace / executes_process，
  │     │    建立 git/fs 恢复快照 (WorkspaceSnapshot.create())
  │     │
  │     ├─ PreToolHookMiddleware: 执行外部钩子 (run_pre_tool_use_hooks)，支持 ALLOW/DENY/FAIL
  │     │
  │     ├─ PermissionMiddleware:
  │     │    ├─ 检查 ToolPermissionStrategy 硬边界与规则
  │     │    ├─ 若需确认 -> 调用 context.confirm_fn (经由 ConfirmationController)
  │     │    └─ 若无人值守超预算 -> 返回 terminate=True 结构化停机信号
  │     │
  │     ├─ EgressGuardMiddleware (可选): 校验网络目标 host 是否命中 EgressWhitelist
  │     │
  │     └─ ReadFreshnessMiddleware:
  │          └─ 若 requires_read_before_write，验证文件已读且 mtime 未被外部篡改
  │
  ▼
[ 5. 工具核心执行体: tool.execute(context, call_id, args, on_update) ]
  │  └─ 封装于 asyncio.create_task 中执行
  │  └─ 工具通过 on_update 异步队列实时推送增量结果 (ToolExecutionUpdateEvent)
  │
  ▼
ToolRuntime 结果与异常拦截
  │  └─ 任何工具抛出的非受检 Exception 均被捕获转为 ToolResult(is_error=True)，
  │     确保 post 链绝对执行，防止 Secret 泄露。
  │
  ├─ 6. Post 中间件管道 (按声明顺序处理结果):
  │     │
  │     ├─ OutputSanitizerMiddleware (可选):
  │     │    └─ 扫描并在输出中抹除敏感凭证 (SecretProvider)，替换为安全 Token
  │     │
  │     ├─ ResultPolicyMiddleware:
  │     │    └─ 由 ResultStore 处理持久化大结果与 snippable 标记
  │     │
  │     └─ AuditMiddleware:
  │          └─ 向 ExecutionAuditLog 记录结构化审计条目 (含 snapshot_id 与授权来源)
  │
  ▼
7. 结果适配与集成
  │  └─ to_core_result(): LionToolResult 转换为 AgentToolResult (保留 terminate/details)
  │  └─ 生成 ToolResultMessage，追加至 AgentHarness._messages
  │  └─ 广播 ToolExecutionEndEvent 及 MessageStart/EndEvent
  ▼
Next Agent Turn (模型接收 ToolResultMessage 作为上下文继续决策)
```

## 核心组件与职责划分

| 组件 | 所属层级 | 核心职责 |
|---|---|---|
| **`ToolRegistry`** | `tooling/` | 管理工具定义集合与实例激活状态 (`_active` 集合)；支持延迟工具 (`deferred=True`) 注册与通过 `tool_search` 动态激活。 |
| **`ToolRuntime`** | `tooling/` | 组装并驱动前置/后置中间件链；提供统一的异常隔离屏障。 |
| **`adapt_lion_tool`** | `adapters/` | 窄腰适配器：将复杂的策略感知 `LionTool` 抹平为纯净的 Core `AgentTool`；防止 Harness 重复执行中间件。 |
| **`PermissionMiddleware`** | `tooling/` | 集中决策只读/写权限、模式匹配与用户交互确认；对接 `PermissionController` 维护已确认缓存。 |
| **`OutputSanitizerMiddleware`** | `tooling/` | 位于 Post 链首位，在工具输出写入 `ResultStore` 或 `ExecutionAuditLog` 前强制脱敏，保证凭证不落盘、不进模型。 |
| **`WorkspaceSnapshot`** | `tooling/` | 在写操作前基于 Git 或临时文件建立文件系统快照，为审计与后续恢复能力保留凭证。 |

## Tool 层与 Kernel 的严格边界

1. **Kernel 零感知策略**：Core 中的 `run_agent_loop` 和 `AgentHarness` 不感知权限、快照、审计、脱敏、工作区或文件新鲜度。Core 仅通过 `AgentTool.execute(call_id, args, signal, on_update)` 调用统一抽象。
2. **动态工具可见性**：Harness 在每一轮次开始时通过 `get_tools` 动态拉取当前激活的工具列表。当工具返回 `added_tool_names`（如 `tool_search` 激活了延迟工具）时，下一轮请求将即刻对模型可见，无需重启或重建 Agent 图。
