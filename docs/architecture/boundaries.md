# 架构边界与依赖约束 (Boundaries)

本文件记录经代码 AST 扫描与 `import-linter` 验证的不可破坏架构边界（唯一事实源：`tests/architecture/_boundaries.py` 与 `pyproject.toml`）。

## 模块依赖矩阵与禁止规则

`_boundaries.py` 使用两种契约模式：**Whitelist 模式**（显式白名单，其余均禁止）与 **Blacklist 模式**（显式黑名单，未列入的模块不限制）。

| 源模块 (`source_package`) | 契约模式 | 允许 / 未禁止依赖 | 明确禁止依赖的模块 (`forbidden`) | 契约原因与边界保证 |
|---|---|---|---|---|
| `lion_code.core` | Blacklist | 除 `forbidden` 外未限制 | `providers`, `tooling`, `application`, `observers`, `tui`, `server`, `sidecar`, `permission_state`, `usage`, `session_runtime`, `capabilities`, `supervisor`, `adapters`, `runtime`, `composition` | 纯内核隔离：Kernel 是轻量级、无状态依赖的状态机与事件契约，不感知任何具体运行时实现。 |
| `lion_code.supervisor` | Blacklist | 公开 Core 契约 (`core.events`, `core.session`) | `runtime`, `application`, `capabilities`, `composition`, `adapters`, `context`, `permission_state`, `providers`, `session_runtime`, `tooling`, `tui`, `server`, `sidecar`, `usage` | 控制平面隔离：Supervisor 作为外层调度器，只能通过 `AgentPort` 观察与控制，禁止触碰 Agent 内部私有对象。 |
| `lion_code.composition` | Blacklist | 除 `forbidden` 外未限制 | `application`, `meta_agent`*, `supervisor`, `tui`, `server`, `sidecar` (*仅 `full_product` 允许构造 facade) | 组装根单向构建：负责将底层基础设施组装成图，不得反向依赖产品外观层或上层 UI。 |
| `lion_code.meta_agent` | Blacklist | 除 `forbidden` 外未限制 | `application`, `supervisor`, `tui`, `server`, `sidecar` | 通用外观：只暴露无特定产品特征的通用 Agent API，不依赖具体应用层或 Supervisor。 |
| `lion_code.providers` | Whitelist | 只允许 `core`, `providers` | 所有其他上层模块（`adapters`, `application`, `capabilities`, `composition`, `context`, `runtime`, `tooling`, `tui` 等） | 供应商适配器纯粹性：只依赖 Core 抽象定义，不感知会话历史、上下文策略或工具管线。 |
| `lion_code.application` | Blacklist | 除 `forbidden` 外未限制 | `tui`, `server`, `sidecar` | 应用层无 UI 耦合：只负责会话管理、命令路由与端口定义，不依赖具体展示端。 |
| `lion_code.tui` | Whitelist | 只允许 `application`, `config`, `core`, `prompt`, `tui`, `version` | 所有其他非白名单模块 | 界面层窄腰接入：终端只能经由 `application` 会话入口与 Core 事件通信，禁止直连引擎。 |
| `lion_code.server` | Whitelist | 只允许 `application`, `config`, `core`, `prompt`, `server`, `version` | 所有其他非白名单模块 | 服务层窄腰接入：HTTP 服务端只能经由 `application` 会话入口与 Core 事件通信。 |
| `lion_code.capabilities` | Blacklist | 除 `forbidden` 外未限制 | `application`, `tui`, `server`, `sidecar` | 插件自治性：业务能力实现通过 SPI 接入，不反向依赖 Agent 宿主环境或前端。 |
| `lion_code` (所有生产代码) | Blacklist | 生产内部模块 | `tests`, `benchmarks` | 严禁生产代码导入测试用例或基准测试套件。 |

## Runtime 内部所有权隔离边界

在 `lion_code.runtime` 内部，对象图保持严格单向且可拓扑排序，杜绝循环引用：

1. **`AgentRuntime` 与 `ProviderController` 互不持有**：
   * `AgentRuntime` 只负责 run 编排（按固定时序调用 `ensure_ready` $\to$ `prepare/compact` $\to$ `prompt`），不持有任何 Provider/Context/Session 的可变状态，也不感知 `ProviderController`。
   * `ProviderController` 拥有 `ProviderState`，只通过 `conversation`, `context`, `recorder` 三个窄端口对外发出命令，严禁持有 `AgentRuntime`。
2. **消灭二段式延时绑定 (`Deferred*`)**：
   * 对象图在 `build_agent_composition` 中一次性构造完成，不存在构造后 `bind()` 的二段式接线。
3. **ContextManager 与 Capability 隔离**：
   * Composition Root 将构建完成的 `ContextLayer` 快照传给 `ContextManager`，`ContextManager` 严禁持有 `CapabilityRegistry` 反向边。
   * `ContextRuntime` 严禁直接持有 `PlanRuntime` 或特定能力的运行时对象。

## Composition 的职责与非职责

* **负责 (What it does)**：
  * 作为唯一的 Composition Root，在 `build_agent_composition` 中汇合 `Profile`、`AgentConfig`、`RuntimeBindings` 三轴输入。
  * 实例化各层 concrete runtime 并拓扑连接。
  * 创建对消费者只读的 `ProviderConfigurationProjection`，供读取面使用而无需持有 Controller。
* **不负责 (What it must NOT do)**：
  * 不包含前端交互与渲染逻辑。
  * 不包含 Supervisor 的目标调度与重试策略。
  * 不保留长生命周期的全局容器，执行完组装即返回 `AgentComposition` 结构体。
