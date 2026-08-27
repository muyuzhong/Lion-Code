# 上下文生命周期与压缩管理 (Context Lifecycle)

本文档描述上下文从消息产生、内存装配、预算裁剪、自动压缩到跨会话延续的完整生命周期。

## 上下文三态模型

```
+-------------------------------------------------------------------------------+
|                       1. 持久化历史 (Durable JSONL)                           |
|   (SessionRepository / SessionRecorder: ~/.lion-code/sessions/<id>.jsonl)     |
|   - Append-only Entry 流: MessageEntry, CompactionEntry, ModelChangeEntry ... |
|   - 永不原地修改，只增不减                                                     |
+-------------------------------------------------------------------------------+
                                      │ SessionState.from_entries() 回放折叠
                                      ▼
+-------------------------------------------------------------------------------+
|                      2. 内存活跃上下文 (Canonical Messages)                     |
|   (ConversationRuntime / AgentHarness._messages)                              |
|   - 包含完整的、未裁剪的当前会话分支原生 AgentMessage 对象                     |
|   - 压缩发生时，通过 replace_active_context() 整体替换为压缩后消息列表         |
+-------------------------------------------------------------------------------+
                                      │ ContextManager.prepare() 深拷贝派生
                                      ▼
+-------------------------------------------------------------------------------+
|                      3. 派生输入上下文 (Prepared Context)                      |
|   (ContextManager 派生产物 -> 传入 Provider.stream_response)                  |
|   - 工具输出预算截断 (Budgeting)                                              |
|   - 过期工具输出打洞裁剪 (Snipping / Clearing)                                |
|   - 动态追加 <agent-state> 状态注入层 (ContextLayer)                           |
+-------------------------------------------------------------------------------+
```

## 生命周期关键阶段

### 1. 消息进入与历史追加
* 用户发送 Prompt 或注入 Steer/Follow-up 消息，作为 `UserMessage` 追加到 `AgentHarness._messages`。
* `SessionRecorder` 监听 `MessageEndEvent`，将完成态消息以 `MessageEntry` 追加写入磁盘 JSONL。

### 2. 上下文装配与预算裁剪 (`ContextManager.prepare`)
每轮 Provider 请求前，`ContextRuntime.prepare_context` 传入活跃消息列表，执行无副作用的派生处理：
* **深拷贝隔离 (`project_messages`)**：防止派生修改污染内存中的权威历史。
* **工具结果预算截断 (`_budget_tool_results`)**：
  * 当窗口利用率 $\ge 60\%$ (`budget_start_ratio`) 时，大工具输出截断为 4000 字符；
  * 当利用率 $\ge 80\%$ (`aggressive_budget_ratio`) 时，激进截断为 1000 字符。
* **过期工具结果打洞 (`_snip_stale_results`)**：
  * 当利用率 $\ge 70\%$ (`snip_start_ratio`) 且模型缓存冷却时，非受保护工具输出替换为 `[... output snipped ...]`。
  * **保护策略**：最近保留轮次（`keep_recent_results=2`）及每个文件最新一次 `read_file` 结果永远受保护。
* **冷缓存清除 (`_clear_old_results`)**：空闲时间超过 300 秒 (`cache_idle_seconds`) 且无缓存命中价值时清空旧输出。
* **ContextLayer 状态注入**：
  * 收集所有注册的 `ContextLayer`（如 `agent_state`、`git_status`、`memory`），渲染结构化文本并作为末尾 `UserMessage`（包含 `<agent-state>...</agent-state>`）附加到派生上下文。

### 3. 上下文压缩触发与执行 (`ContextCompactor`)
当窗口利用率达到 `auto_compact_ratio` (80%)、发生模型溢出或用户手动执行 `/compact` 时触发：

```
1. 确定边界 (_recent_context_boundary)
   └─ 默认保留最近 1 个用户轮次边界（溢出时保留 2 个），严禁拆散 ToolCall 与 ToolResult 对。

2. 结构化摘要提取 (ProviderContextCompactor.summarize)
   └─ 调用 ModelProvider 按照固定 9 大章节协议生成严密摘要：
      # Objective / # Constraints / # Decisions / # Repository State /
      # Findings / # Failed Attempts / # Completed Work / # Remaining Work / # Verification

3. 写入压缩记录 (SessionRuntime.record_compaction)
   └─ 向 JSONL 追加 CompactionEntry(summary=..., replaces_entry_ids=[...])。

4. 活跃上下文重载 (replace_active_context)
   └─ 重新从 Session 加载消息：被替换的旧 Entry 在内存中折叠为：
      UserMessage("Previous conversation summary:\n<summary>") + 最近保留的消息。

5. 状态复位
   └─ UsageLedger.reset_context_tracking() 重置上下文统计，ContextRuntime.on_compacted() 清除压缩标记。
```

### 4. 轮次间与会话间延续
* **同会话轮次延续**：Harness 在本轮工具执行完毕后，直接将 `AssistantMessage` 和 `ToolResultMessage` 保留在 `_messages` 中，供下一轮继续使用。
* **跨进程/新会话恢复**：
  * `SessionRuntime.load(session_id)` 从 JSONL 文件自底向上回放 Entry 树，折叠所有 `CompactionEntry`；
  * `ConversationRuntime.replace_active_context(state.messages)` 一次性装载恢复的消息，无缝接续。
