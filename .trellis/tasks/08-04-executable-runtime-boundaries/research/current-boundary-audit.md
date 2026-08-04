# 当前运行时边界审计（2026-08-04）

## 命令与结果

执行：

~~~text
lint-imports --no-cache
~~~

结果：分析 150 个文件、750 条依赖；现有 3 条合同均为 KEPT，0 broken。

当前合同位于 pyproject.toml：

1. TUI 不直接依赖 memory_runtime 与 session_runtime。
2. Application 不依赖 TUI。
3. 产品代码不导入 tests 与 benchmarks。

.github/workflows/ci.yml 已把 lint-imports --no-cache 作为失败即阻塞的质量门禁。

## 当前依赖事实

### Core

对 lion_code/core 进行 providers、tooling、application、tui 的绝对导入扫描，结果为空。因此 Core 上行依赖合同能从当前状态开始收紧。

### Providers

providers 中所有绝对 Lion 导入均落在 lion_code.core：

- provider.py 使用 core.provider。
- config.py、retry.py 使用 core.types。
- events.py 使用 core.provider_events。
- fake.py、anthropic.py、openai_compatible.py、stream.py 使用 core 的 message、tool、provider 或 type 模型。

当前没有 providers 到 application、tooling、session_runtime、memory_runtime、tui 或 Agent 的绝对产品导入。

### Application 与 TUI

application 不导入 lion_code.tui。

TUI 的运行时相关导入来自 application 和 core。它还直接使用 config、prompt、version，分别承担配置持久化、项目上下文展示和版本文本；这些不是对 Agent runtime 的命令或输出旁路。TUI 当前没有到 providers、tooling、memory_runtime 或 session_runtime 的直接导入。

## 消息、Session 与 Memory 所有权

### Canonical history 与 Provider

LionAgentRuntime.messages 返回 harness.messages。Provider 的 stream_response 收到 messages 参数后构建当前请求，未在实例字段中保存 messages/history。FakeProvider 仅记录 calls 供测试断言。

### Session Writer

生产代码中 SessionRecorder 的构造调用有两个：

1. lion_code/agent_runtime.py 的 AgentRuntimeCoordinator.reset_core_observers：为非子 Agent 创建当前会话唯一活跃 recorder，并订阅 Core runtime。
2. lion_code/agent.py 的 Agent._migrate_legacy_core_session：把历史 JSON 只读转换结果写入同 ID 的 JSONL；完成后正常会话仍由 coordinator 的 recorder 接续。

第二处是迁移兼容性例外，不能被误判为第二条活跃 runtime writer 路径。

### Memory Overlay

MemoryContextInjector.inject 先 project_messages(messages)，然后把 overlay 拼接到临时 projection；它不改写传入 messages。既有 tests/memory_runtime/test_injector.py 的 test_overlay_is_ephemeral_and_each_projection_contains_one_block 断言输入 snapshot 不变且 relevant-memory 标记仅存在于 projection。

AgentRuntimeCoordinator.prepare_core_context 将这个临时 projection 返回给 Provider。session_memory_coordinator 可以读取 _core_runtime.messages 的本轮切片以做会后更新，但不调用 Harness 的 replace/queue/clear API。

### 历史残留

_openai_messages 和 _anthropic_messages 只在 lion_code/session_runtime/legacy.py 中定义并由旧 JSON 迁移调用。产品代码中没有 ui.set_sink 或 set_sink 调用。

## 设计结论

import-linter 适合稳定的包级方向；它无法约束实例字段、函数构造点和调用符号。新 AST architecture 测试应精确检查上述例外，避免把 legacy 迁移、FakeProvider 测试探针或 TUI 展示辅助模块误判成架构回归。
