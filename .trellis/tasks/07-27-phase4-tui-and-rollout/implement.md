# B5 实施计划

1. 在 `Agent` 现有 Core 压缩实现上增加强制 overflow 恢复入口；强制路径保留
   最近两个用户边界（最近成功轮次 + 本次失败 prompt），阈值路径保持原语义。
2. 在 `LionCodingSession._drive()` 中记录本次 Core run 的终态 Assistant 错误：
   仅首次 overflow 进入压缩与重试，映射 `SessionAgentEnd.will_retry`。
3. 压缩成功后复用当前 `LionAgentRuntime.continue_()`，发出
   `Compaction*`、`AutoRetry*` 和最终 `AgentSettled`；失败、取消和二次错误均
   收敛为有限终态。
4. 添加应用层回归测试，断言严格事件顺序、单次重试上限、durable
   `CompactionEntry`、重试 Provider 上下文及失败分支。
5. 运行 application/context/session/runtime/provider/tui 相关测试，再运行全量
   pytest、compileall、ruff（若环境已有）与 `git diff --check`。
