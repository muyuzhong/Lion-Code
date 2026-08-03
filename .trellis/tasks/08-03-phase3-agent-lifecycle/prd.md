# 三阶段-5：提取 Agent 生命周期

## Goal

将 Provider 配置与 Thinking 档位的生命周期协调从 `Agent` 提取到
`AgentLifecycle`，保持模型/凭证热切换、Core history、Memory side-query 与会话记录的
既有不变量。

## Confirmed Facts

- 当前配置职责集中在 `agent.py`：`api_configured`、`get_api_config()`、
  `configure_api()`、`set_thinking()`、Thinking 档位 getter/setter/cycle、
  `_build_core_provider()` 和 `_apply_core_thinking_level()`。
- `configure_api()` 只允许空闲态执行；先构建 replacement Provider、compactor 与
  query service，成功后才替换 Core Provider 和配置字段，因此构建失败不会破坏旧状态。
- Provider 热替换保留同一个 `LionAgentRuntime` 和 canonical Core messages，旧 Provider
  的 `aclose()` 经既有 background-operation 队列延后回收；新的 query service 必须
  重新绑定给 MemoryCoordinator。
- 现有测试大量 patch `lion_code.agent.create_provider` 注入 FakeProvider。迁移必须
  保留该测试/兼容锚点，不能让配置代码直接改为绑定新模块的 factory。
- `set_terminal_output()`、观察器重建、后台任务队列、`close()` 与 Session 恢复仍与
  UI/Core/资源聚合交叉；它们不属于本次约 200 行的 Provider 配置提取范围。

## Requirements

- R1：新增 `lion_code/agent_lifecycle.py`，由它拥有 Provider 配置解析、原子替换、
  Thinking 模式/档位变更、缓存刷新、Memory query-service 重绑及会话配置记录调度。
- R2：`Agent` 保留所有既有 public API 和必要私有入口作为薄委托，初始化时创建
  `AgentLifecycle` 并通过它构建初始 Core Provider。
- R3：运行时只通过窄 Host 协议读写 Agent 持有的 Core、Memory、配置和 recorder；
  不反向导入 `Agent`，不创建第二份 history、Provider 或 Session writer。
- R4：保留 `lion_code.agent.create_provider` 作为动态 Host factory 回调，确保现有
  FakeProvider patch 在构造、切换模型和切换 Thinking 时仍然生效。
- R5：保持 busy-state 拒绝、replacement 构建失败回滚、model-only 不重建 Provider、
  旧 Provider 延后关闭、Thinking 持久化和子 Agent 当前 API 继承行为不变。

## Acceptance Criteria

- [ ] AC1：`AgentLifecycle` 独立拥有上述 Provider/Thinking 配置流程，`agent.py` 只保留
  组装、Host factory 和公共兼容委托。
- [ ] AC2：`configure_api()` 在忙碌时或 replacement 构建失败时保持原 Provider、配置和
  canonical history；成功切换后原 Runtime 身份和消息不变。
- [ ] AC3：model-only 切换不重建 Provider；协议/凭证/base 切换和 Thinking 档位切换均
  刷新 compactor 与 Memory query service，并异步关闭旧 Provider。
- [ ] AC4：既有 `lion_code.agent.create_provider` patch 继续覆盖初始构造、API 切换与
  Thinking 重建；新模块不在模块级导入 `Agent`。
- [ ] AC5：Session recorder 继续记录 model/Thinking 变更；`_child_api_kwargs()` 继续在
  fork 时读取当前 API 配置。
- [ ] AC6：相关 integration/application/tooling 回归、完整测试、compileall、导入边界、
  改动范围静态检查、差异检查与 Trellis validation 均通过，并如实记录基线差异。

## Out of Scope

- `set_terminal_output()`、`_reset_core_observers()`、后台任务队列、`close()`、
  Session restore/clear 与 Core 对话循环的重构。
- 改变 Provider 选择、环境变量回退、Thinking 词汇、权限语义、Session JSONL 格式或
  TUI `/model`、`/thinking` UX。
- 清理既有 Ruff/format/mypy 基线或引入 Provider SDK。

## Planning Status

阻塞问题为空。此切片采用 Provider 配置生命周期的窄范围，避免把 UI 观察器与全局资源
关闭一并混入；已完成复杂任务所需的设计与实施计划，等待用户明确批准后才启动并改代码。
