# 第四阶段：运行时边界可执行约束设计

## 1. 目标与边界

本任务不改变运行时行为。它把现有 Runtime Boundary 文档中的禁止关系拆成两类可执行防线：

1. import-linter 负责包级直接和间接依赖方向。
2. pytest 中的 AST 架构测试负责 import 图看不到的符号、构造点和消息所有权约束。

CI 已无条件执行 lint-imports，因此新合同自动成为合并门禁；architecture 测试由既有 pytest 步骤覆盖。

## 2. Import-linter 合同

pyproject.toml 的合同调整为以下五条：

| 合同 | 机制 | 保护的回归 |
| --- | --- | --- |
| Core 不依赖上层运行时包 | forbidden，禁止 providers/tooling/application/tui，含间接路径 | Core 被 Provider、工具或前端反向耦合 |
| Providers 只依赖 Core 抽象 | forbidden，禁止其余 Lion 运行时层 | Provider 自建 Agent、工具、Session 或 UI 路径 |
| Application 不依赖 TUI | forbidden | use-case 层反向持有 Textual |
| TUI 只经 application/core 接触运行时 | forbidden，禁止 Provider/Tooling/Memory/Session/Agent runtime 等引擎层 | 前端绕过事件边界 |
| 产品不反向引用 tests/benchmarks | 现有 forbidden 合同保留 | benchmark/test 代码进入产品路径 |

TUI 仍可直接使用 config、prompt、version 等展示辅助模块。这不是对 Agent 运行时的命令或输出依赖；严格禁止的是绕过 application/core 的运行时引擎入口。

Providers 还会由 AST 测试施加闭世界检查：绝对 Lion 导入只能以 lion_code.core 开头，且相对导入不得越出 providers。这弥补 forbidden 列表未来新增顶级包时的遗漏风险。

## 3. Architecture 测试设计

新增 tests/architecture/test_runtime_boundaries.py。测试解析 lion_code 下的 Python AST，不导入产品模块，以避免测试本身触发外部 Provider 或 Textual 初始化。

### 3.1 导入边界辅助函数

- 枚举产品源码，排除 __pycache__。
- 将绝对 lion_code 导入归一化为顶级包名。
- 将相对导入限制在当前包；providers 的越级相对导入即失败。
- 将 TUI 的运行时可见产品导入限制为 application、core、config、prompt、version。

import-linter 仍是依赖图权威；该辅助函数只承担“允许集合必须封闭”的语义补强。

### 3.2 禁止符号与精确例外

| 规则 | AST 检查 | 允许例外 |
| --- | --- | --- |
| Provider 私有历史 | Provider 类不得给 self 写入名称含 messages 或 history 的字段 | FakeProvider 的 calls 是测试探针，不是消息字段 |
| 旧消息路径 | _openai_messages / _anthropic_messages 的定义和引用只能出现在 session_runtime/legacy.py | legacy.py 仅用于旧 JSON 只读转换 |
| 全局 UI Sink | 产品源码不得定义或调用 set_sink | 无 |
| Session Writer | SessionRecorder 只能由 agent_runtime.py:reset_core_observers 和 agent.py:_migrate_legacy_core_session 直接构造；禁止别名和属性形式绕过 | 后者一次性写入旧格式迁移，非活跃 runtime writer |
| 绕过 JSONL writer | JsonlSessionStorage 的写 API 不得被非 core/session 或 session_runtime 模块直接持有/调用 | SessionRecorder 与 core/session 的实现 |
| Memory Overlay 写 Core | memory_runtime 和 session_memory_coordinator 不得引用 AgentHarness，也不得调用 replace_messages、follow_up、clear_queues 等 Harness mutation API | 它们可读取 canonical snapshot 并返回临时 projection |

所有例外都在测试常量和 Runtime Boundary 规范中同步说明，防止后续贡献者把例外误认为漏洞或复制成新入口。

### 3.3 Memory Overlay 的行为验证

不新建重复的 Agent 集成闭环。既有 tests/memory_runtime/test_injector.py::test_overlay_is_ephemeral_and_each_projection_contains_one_block 已验证输入 messages 未改写且 overlay 标记只出现在 projection。本任务让架构扫描阻止对 Harness mutation API 的新增访问；二者共同覆盖行为和结构。

## 4. 兼容性、风险与回滚

- 运行时代码零修改，所有变化仅收紧开发时门禁。
- legacy JSON 迁移构造点是唯一兼容性例外；若以后迁移职责迁入 coordinator，应先更新规范与 allowlist，再移动代码。
- AST 测试使用语法节点而非文本，因此注释、文档或字符串中的术语不触发假失败。
- 回滚只需撤销本任务修改的 pyproject、测试和文档；不会影响用户的 session 文件或产品运行时。
