# B5 设计：溢出压缩与一次自动重试

## 当前状态

- `application/events.py` 已定义 `CompactionStart/End`、
  `AutoRetryStart/End` 与 `SessionAgentEnd.will_retry`，TUI adapter 也已消费
  `AutoRetryStartEvent`，但运行时没有发出这些事件。
- Core 将 Provider 失败收敛为
  `MessageEndEvent(AssistantMessage(stop_reason="error"))`，随后仍发出
  `AgentEndEvent`；错误消息会由 `SessionRecorder` 持久化。
- `Agent._compact_core_context_if_needed()` 已能用 Provider-neutral compactor
  写 `CompactionEntry` 并替换 Harness 活跃上下文，但只受 85% 阈值触发，
  无法在 Provider 已报告 overflow 后强制执行。
- `LionCodingSession._drive()` 已是应用级事件与 `AgentSettledEvent` 的唯一
  owner，适合承接一次溢出恢复；不需要新增 Agent→application 反向回调。

## 数据流与顺序契约

```text
Core MessageEnd(error: overflow)
  → Core AgentEnd
  → SessionAgentEnd(will_retry=True)
  → CompactionStart(overflow)
  → Agent 强制压缩（保留最近成功轮次与本次失败 prompt）
  → CompactionEnd(will_retry=True)
  → AutoRetryStart(attempt=1, max_attempts=1, delay_ms=0)
  → 复用同一 LionAgentRuntime.continue_()
  → SessionAgentEnd(will_retry=False)
  → AutoRetryEnd(success=是否正常完成)
  → AgentSettled
```

## 边界决策

1. 溢出识别只读取 canonical `AssistantMessage.error_message`，采用 Tau 已验证的
   context-length/window/token-limit 文本标记；普通 Provider 错误不触发恢复。
2. 自动恢复最多一次且无延迟。重试再次失败时发
   `AutoRetryEnd(success=False)` 后归位，不循环。
3. 压缩失败或用户在压缩阶段取消时发
   `CompactionEnd(aborted=True, will_retry=False)`，不启动重试，仍发 Settled。
4. 原始 overflow error 保留在 append-only history；Core 既有 Provider 投影会
   过滤空的失败 Assistant 消息，重试请求只看到压缩后的有效上下文。
5. 不改 Core `AgentEvent` 联合、不实现第二套 Loop/存储、不接管 Provider 内部
   网络重试，也不扩展 legacy SDK 路径。

## 修改面

- `lion_code/agent.py`：为既有 Core 压缩路径增加 overflow 强制入口；正常阈值
  压缩行为不变。
- `lion_code/application/session.py`：识别 overflow 并在同一个 `_drive` 生命周期
  内完成压缩、一次 continue 与应用事件排序。
- `tests/application/test_coding_session.py`：覆盖成功恢复、压缩失败/取消、重试失败
  与非 overflow 不重试。
