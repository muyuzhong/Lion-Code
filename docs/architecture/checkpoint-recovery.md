# 检查点与恢复机制 (Checkpoint & Recovery)

本文档基于代码中实际实现的两种持久化机制进行说明：**Supervisor 控制平面 Checkpoint** 与 **Session 数据平面 Transcript**。

## 两种 Checkpoint 对比矩阵

| 维度 | Supervisor Checkpoint (控制平面) | Session Transcript (数据平面) |
|---|---|---|
| **源码路径** | `lion_code/supervisor.py` (`SupervisorState`) | `lion_code/session_runtime/` + `core/session/` |
| **持久化目标** | 长期自治目标、尝试次数、重试阶段与任务调度状态。 | 对话历史、消息条目、模型/思考档位配置、压缩摘要。 |
| **存储介质与格式** | 原子写入单个 JSON 文件 (`~/.lion_code/checkpoints/<goal_id>.json`)。 | Append-only 顺序追加 JSON Lines (`~/.lion-code/sessions/<session_id>.jsonl`)。 |
| **触发时机** | 1. 目标创建 (`pending`)<br>2. 每轮尝试开始 (`running`)<br>3. 关联 `session_id` 时<br>4. 尝试结束 (`retry_wait` / `completed` / `failed` / `cancelled`) | 1. 产生完成态消息 (`MessageEntry`)<br>2. 发生模型变更 (`ModelChangeEntry`)<br>3. 发生思考档位变更 (`ThinkingLevelChangeEntry`)<br>4. 上下文压缩 (`CompactionEntry`)<br>5. 标记标题 (`LabelEntry`) |
| **保存的字段** | `goal_id`, `goal`, `phase`, `status`, `attempt`, `session_id`, `retry_count`, `last_stop_reason`, `last_error`, `created_at`, `updated_at`, `next_run_at` | `SessionInfoEntry` (cwd), `MessageEntry` (AgentMessage), `CompactionEntry`, `ModelChangeEntry`, `ThinkingLevelChangeEntry`, `LabelEntry` |
| **明确不保存的内容** | 严禁保存对话内容、消息体、Tool 输出、Token 用量、内存队列与 Provider 密钥。 | 增量打字事件 (`MessageUpdateEvent`)、内存临时队列 (`steering`/`follow_up`)、未结束工具执行体。 |

## 恢复流程 (Recovery Flow)

### 1. Supervisor 自治任务恢复 (`Supervisor.run`)
```
1. 读取 Checkpoint (JsonCheckpointStore.load(goal_id))
   ├─ 若文件不存在 -> 创建初始 SupervisorState (phase="pending")
   └─ 若已处于终态 (completed / failed / cancelled) -> 直接返回结果，不重复执行。

2. 阶段校验与等待
   └─ 若 phase == "retry_wait" -> 调用 Scheduler.wait() 休眠至 next_run_at 时间戳。

3. 构造干净的 Agent 实例 (agent_factory())
   └─ 若 state.session_id 存在 -> 调用 agent.restore(state.session_id)。

4. 执行目标尝试 (agent.run(prompt))
   └─ 关联本次运行生成的 session_id 并立即持久化 Checkpoint。
```

### 2. Session 会话回放与恢复 (`AgentRuntime.restore`)
```
1. 仓库加载与回放 (SessionState.from_entries(entries, leaf_id=...))
   ├─ 默认模式：按存储顺序（Storage Order）线性回放全部 Entry。
   ├─ 分支模式：若显式传入 leaf_id，则仅沿 root-to-leaf path 进行路径回放。
   └─ 压缩折叠：遇到 CompactionEntry 时，将 replaces_entry_ids 中的旧消息
      折叠替换为一条 UserMessage("Previous conversation summary:\n<summary>")。

2. 跨 Owner 恢复
   ├─ ProviderController.restore_configuration(model, thinking_level): 恢复模型档位
   └─ ConversationRuntime.replace_active_context(state.messages): 重建 Harness 活跃消息

3. SessionRuntime 重置 Recorder
   └─ SessionIdentityState.reset(session_id, started_at)，恢复写入位置。
```

## 异常与停机场景行为差异

| 场景 | Supervisor 状态变化 | Agent / Session 状态 | 恢复行为 |
|---|---|---|---|
| **崩溃 / 掉电 (Crash / Process Kill)** | Checkpoint 停留在 `phase="running"`。 | JSONL 中已写入的 Entry 安全保留；未完成的 ToolCall 会在下次启动由 Harness 自动补齐合成错误消息。 | 重新运行 Supervisor 时，加载到 `running` 状态，递增 `attempt`，通过 `session_id` 恢复已有历史继续运行。 |
| **主动取消 (Cancellation)** | `Supervisor.cancel()` 触发，Checkpoint 写入 `phase="cancelled", status="cancelled"`。 | `ExecutionControl.cancel()` 停止当前流；Harness 补齐合成结果后安全退出。 | 终态不可恢复；再次调用 `Supervisor.run()` 直接返回 `cancelled` 结果，绝不自动重试。 |
| **可重试故障 (Retryable Failure)** | 若 `last_stop_reason` 命中 `RetryPolicy`（如 `timeout`, `model_error`）且未超上限：写入 `phase="retry_wait", next_run_at=now+delay`。 | 会话历史保留故障前的完整上下文。 | 调度器等待退避时间后，启动下一次 attempt 重新进入执行。 |
| **不可重试故障 (Fatal Failure)** | 若未命中策略（如代码逻辑错误、预算超额、达到最大尝试次数）：写入 `phase="failed", status="failed"`。 | 会话历史保留故障诊断信息。 | 终态不可恢复；终止调度。 |

## 当前代码事实与未实现项说明

* **原子替换而非多写并发互斥**：`JsonCheckpointStore` 使用临时文件配合 `os.replace()` 实现单个文件写入的原子替换（读取者不会读到半写入的脏数据），但系统**未实现文件锁或多写互斥锁**；若多个进程同时写入同一个 `goal_id`，后写入者将直接覆盖先写入者（Lost Update）。
* **进程内协程热恢复 (Live Coroutine Hot-Resume)**：当前未实现工具执行中途的内存断点恢复。若进程在工具执行期间被强杀，恢复时从上一个已持久化的轮次边界（即工具调用发起点）重新执行。
