# Agent 循环与轮次执行链路 (Agent Loop)

本文档按照真实执行顺序描述 Lion-Code 单次 Agent 运行（Operation）及单轮（Turn）的生命周期。

## 执行链路时序图

```
User / Caller (AgentRuntime.chat / run)
  │
  ├─ 1. 准备阶段: ExecutionControl.begin() -> ensure_ready() (清理后台任务/解析限制/初始化Recorder)
  │
  ├─ 2. 压缩检查: compact_if_needed() (若超阈值则调用 ContextRuntime.summarize 并重写活跃上下文)
  │
  ├─ 3. Harness 入口: ConversationRuntime.prompt() -> AgentHarness._run()
  │     │
  │     ├─ 发送 AgentStartEvent, TurnStartEvent, MessageStart/EndEvent (Prompt)
  │     │
  │     ▼
  │  [ Turn 循环开始 (core/loop.py: run_agent_loop) ] ◄─────────────────────────┐
  │     │                                                                     │
  │     ├─ 4. 每轮动态解析:                                                     │
  │     │    ├─ get_tools(): 从 ToolRegistry 解析当前激活工具 (含延迟工具/技能工具)   │
  │     │    ├─ get_system(): 从 PromptComposer 组装提示词与 Capability PromptLayer  │
  │     │    └─ prepare_context(): ContextManager 裁剪工具结果并追加 <agent-state>    │
  │     │                                                                     │
  │     ├─ 5. Provider 流式生成: provider.stream_response()                    │
  │     │    └─ 实时产出 MessageStart/Update/EndEvent，收集 AssistantMessage    │
  │     │    └─ [异常分支]: 若 stop_reason 为 error/aborted，触发收尾事件并退出   │
  │     │                                                                     │
  │     ├─ 6. 工具调用前预算闸门: before_tool_calls(assistant)                  │
  │     │    └─ AgentRuntime.before_core_tool_calls: 记录 turn，检查用量预算   │
  │     │    └─ [超预算分支]: 注入合成错误 ToolResultMessage 并终止运行          │
  │     │                                                                     │
  │     ├─ 7. 工具分批与执行: _tool_call_batches()                              │
  │     │    ├─ 串行/并行批次划分 (仅 concurrency_safe+read_only 可并行)         │
  │     │    ├─ adapt_lion_tool -> ToolRuntime.execute() (经由中间件管道执行)   │
  │     │    └─ 产生 ToolExecutionStart/Update/EndEvent 及 ToolResultMessage   │
  │     │                                                                     │
  │     ├─ 8. 轮次终态收敛: TurnEndEvent (附带 tool_results)                    │
  │     │    ├─ 若有工具调用且未触发 terminate 标志 ── 继续下一轮 ───────────────┘
  │     │    ├─ 若执行期间有 steer 消息 ── 立即作为下一轮消费 ────────────────────┘
  │     │    └─ 若无工具调用且有 follow_up 消息 ── 取出并继续循环 ─────────────────┘
  │     │
  │     ▼
  │  [ Turn 循环结束 ]
  │
  ├─ 9. 收尾阶段:
  │     ├─ 发送 AgentEndEvent
  │     ├─ AgentRuntime.sync_conversation_outcome(): 映射对外 stop_reason
  │     └─ ContextRuntime.evaluate_compaction_required(): 重估压缩标记
  │
  ▼
Caller 获得执行结果 (AgentRunResult / 事件流结束)
```

## 控制权转移与状态更新节点

| 阶段 | 控制权所在 | 状态更新发生地 | 产生/广播的事件 |
|---|---|---|---|
| **1. 准备** | `AgentRuntime` | `ExecutionControl`（重置令牌）、`SessionRuntime`（Recorder ready） | 无 |
| **2. 自动压缩** | `AgentRuntime` / `ContextRuntime` | `SessionRuntime`（追加 `CompactionEntry`）、`ConversationRuntime`（替换活跃消息） | `CompactionStartedEvent`, `CompactionCompletedEvent` |
| **3. 启动** | `AgentHarness` | `AgentHarness._running = True` | `AgentStartEvent`, `TurnStartEvent`, `MessageStart/EndEvent` |
| **4. 上下文准备** | `ContextManager` | 无（深拷贝消息列表，纯函数式派生输入） | 无 |
| **5. 模型流** | `ModelProvider` | `ConversationRuntime.capture_event`（捕获流式文本增量） | `MessageStartEvent`, `MessageUpdateEvent`, `MessageEndEvent` |
| **6. 预算拦截** | `AgentRuntime` | `UsageLedger.record_turn`（累加轮次） | 超预算时发 `MessageStart/EndEvent`, `TurnEndEvent`, `AgentEndEvent` |
| **7. 工具执行** | `ToolRuntime` | `ReadFreshnessMiddleware`（更新文件 mtime）、`ExecutionAuditLog`（记录审计）、`ResultStore`（存储大输出） | `ToolExecutionStart/Update/EndEvent`, `ToolResultMessage` 的 `MessageStart/EndEvent` |
| **8. 结果集成** | `core/loop.py` | `AgentHarness._messages`（追加 `AssistantMessage` 与 `ToolResultMessage`） | `TurnEndEvent` |
| **9. 收尾** | `AgentRuntime` | `UsageLedger`（Token 结算）、`AgentRuntime._last_stop_reason` | `AgentEndEvent` |

## 终止条件与轮次控制 (Termination & Turn Control)

循环在满足以下任一条件时正常或异常终止：

1. **自然完成 (`completed`)**：模型未发起任何工具调用，且 Harness 的 `steering` 和 `follow_up` 队列均为空。
2. **工具显式终止 (`terminate=True`)**：如无人值守模式下权限策略判定超出预算，工具返回结构化停机信号。
3. **用量预算拦截 (`max_cost` / `max_turns`)**：在工具调用边界，`AgentRuntime.before_core_tool_calls` 通过 `BudgetPolicy.check()` 检测到超额，合成错误消息阻止工具执行并终止。
4. **Kernel 最大轮次控制 (`max_turns`)**：`core/loop.py` 内部接收 `max_turns` 参数；若 `turn > max_turns`，产出错误消息并退出。在产品组装层，`ConversationRuntime` 默认传入安全兜底值（`ITERATION_SAFETY_CAP = 200`）防止纯文本无限死循环。
5. **模型/网络异常 (`model_error`)**：Provider 返回 `AssistantErrorEvent`。
6. **主动取消/中止 (`aborted`)**：`ExecutionControl.cancel()` 触发，或 Provider 报告中断。

## 错误与取消传播机制

* **工具异常隔离**：`ToolRuntime` 捕获工具执行体抛出的所有异常，将其转为 `ToolResult(is_error=True)`，随后继续走完 post 中间件链（确保 Secret 脱敏和审计落盘），模型在下一轮可见该错误文本并可自行纠错。
* **取消信号传播**：`CancellationToken` 贯穿 Harness、Provider 流与 `ToolContext`。取消触发后：
  1. Provider 流式生成即刻中止。
  2. 正在运行的工具协程被 cancel。
  3. `AgentHarness._append_interrupted_tool_results()` 自动扫描并为未完成的 `ToolCall` 补齐合成的 `ToolResultMessage`，确保历史消息中 ToolCall 与 ToolResult 严格成对，杜绝损坏后续 Provider 请求。
