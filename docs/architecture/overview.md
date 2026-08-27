# Lion-Code 架构总览 (Overview)

Lion-Code 是一个模块化、供应商无关、严格分层的编码 Agent 框架。

## 整体架构与分层

```
+-------------------------------------------------------------------------------+
|                             Supervisor 平面                                   |
|   (supervisor.py: 长期目标编排、重试调度、Checkpoint 状态机，仅依赖公开 AgentPort)     |
+-------------------------------------------------------------------------------+
                                      │ 消费公开 run / restore / cancel
                                      ▼
+-------------------------------------------------------------------------------+
|                    Interfaces & Product Adapters 边界                         |
|   (tui/, server/, sidecar.py, application/, adapters/coding_session_backend)  |
+-------------------------------------------------------------------------------+
                                      │
                                      ▼
+-------------------------------------------------------------------------------+
|                               Composition 根                                  |
|   (composition/agent_builder.py: 汇合 Profile / Config / Bindings 一次性组装图) |
|   (meta_agent.py: 零扩展 MetaAgent 通用 Facade)                                |
+-------------------------------------------------------------------------------+
        │                                  │                        │
        │ 构造装配                          │ 注册 SPI 扩展           │ 注入 ContextLayer 快照
        ▼                                  ▼                        ▼
+-----------------------+     +--------------------------+     +----------------+
|     Agent Runtime     |     |       Capabilities       |     |  Tool Runtime  |
| (runtime/ 编排与三大 Owner) |  │ (capabilities/ 业务插件) │     | (tooling/ 管线)|
+-----------------------+     +--------------------------+     +----------------+
        │                                                           │
        └──────────────────────────┬────────────────────────────────┘
                                   │ 驱动纯内核
                                   ▼
+-------------------------------------------------------------------------------+
|                             Minimal Agent Kernel                              |
|   (core/: loop.py, harness.py, messages, events, session JSONL 格式定义)      |
|   (context/: manager, compaction, projector; providers/: 流式协议实现)         |
+-------------------------------------------------------------------------------+
```

## 六大核心层职责与定位

| 层级 | 源码路径 | 核心职责 | 绝对禁止项 |
|---|---|---|---|
| **Kernel** | `lion_code/core/`, `context/`, `tooling/`, `providers/`, `session_runtime/`, `usage.py`, `permission_state.py` | 提供纯粹的 Agent Loop、Harness 状态机、上下文预算/压缩模型、工具执行管线、供应商适配与 JSONL 存储格式。 | 禁止导入任何上层运行时；禁止包含 Capability/Supervisor 专属符号。 |
| **Agent Runtime** | `lion_code/runtime/` | 状态所有权拆分层。划分 `ConversationRuntime`、`SessionRuntime`、`ContextRuntime` 三大 Owner，以及 `AgentRuntime`（编排者）与 `ProviderController`（命令者）。 | `AgentRuntime` 与 `ProviderController` 双向禁止引用；禁止维护第二份消息历史；禁止反向依赖上层。 |
| **Capabilities** | `lion_code/capabilities/` | 可插拔扩展层。通过 `CapabilitySpec` SPI 向 Composition 提供工具、ContextLayer、PromptLayer 和会话生命周期钩子。 | 禁止感知 Agent 宿主、Application、TUI、Server；禁止跨 capability 紧耦合。 |
| **Composition** | `lion_code/composition/`, `meta_agent.py` | 组装根。汇合 Profile (形态)、AgentConfig (策略) 与 RuntimeBindings (基础设施)，单向拓扑构建对象图并包装为 `MetaAgent`。 | 禁止包含前端逻辑、Supervisor 策略；禁止泄露私有运行时对象。 |
| **Product / Interfaces** | `lion_code/application/`, `adapters/`, `tui/`, `server/`, `sidecar.py` | 终端/网络/桌面交互界面与产品适配。消费 `application/ports.py` 语义契约，处理终端输出、命令解析、会话枚举与溢出重试。 | 禁止直接持有 Core 私有运行时；禁止直接绕过 Application 接触底层。 |
| **Supervisor** | `lion_code/supervisor.py` | 外部自治控制平面。管理目标生命周期、指数退避重试、JSON 执行控制 Checkpoint 与 Agent 崩溃恢复。 | 严格黑盒化：只通过公开 `AgentPort` 交互，禁止读取 Agent 内部队列与私有字段。 |

## 最小 Kernel 与可选扩展划分

* **最小 Agent Kernel（核心不可剪裁集合）**：
  * `core/loop.py` (`run_agent_loop`): Pi 兼容的单轮/多轮流式驱动循环。
  * `core/harness.py` (`AgentHarness`): 状态机封装、取消令牌、流中插入 (steer/follow-up)、事件广播。
  * `context/`: `ContextManager` (上下文预算与裁剪)、`ContextCompactor` (结构化历史摘要)。
  * `tooling/`: `ToolRegistry`、`ToolRuntime`、标准中间件链 (权限/取消/快照/审计/脱敏)。
  * `providers/`: 统一流式供应商抽象 (`AnthropicProvider`, `OpenAICompatibleProvider`)。
  * `session_runtime/`: append-only JSONL 会话存储与重放。
* **产品可选扩展 (Optional Capabilities)**：
  * `MinimalProfile`: 零内置 Capability，仅包含调用方提供的基础工具。
  * `CodingProfile`: 增加内置 Coding 工具（文件/命令）、`agent_state` 与 `git_status` ContextLayers。
  * `FullProfile`: 进一步包含 `plan` (计划模式)、`subagent` (子代理)、`skill` (动态技能)、`memory` (SQLite 语义记忆库)。

## 依赖流向法则

系统严格遵循单向依赖，禁止任何逆向或环形依赖：

$$\text{Supervisor} \longrightarrow \text{Interfaces} \longrightarrow \text{Composition} \longrightarrow \text{Runtime / Capabilities / Tooling} \longrightarrow \text{Kernel}$$
