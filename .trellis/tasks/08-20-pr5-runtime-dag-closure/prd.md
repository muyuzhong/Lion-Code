# PR5 — Runtime DAG Closure and Architecture Seal

## Goal

完成 PR1–PR4 之后的最终架构收口：消除 Provider configuration 的 hidden
late-bound closure，使 Runtime object graph 成为可从 Composition Root 一次
拓扑构造的真实 DAG；同时把 Full product composition factory 从 Product Adapter
模块移到 `lion_code/composition/` 的明确 bootstrap 位置。

用户价值是让 Runtime ownership、Provider ownership 和 Product Adapter 边界都
能通过可达对象图与静态门禁证明，而不是依赖字段命名或约定。

## 已确认事实

- 当前工作区位于 PR4 分支 `muyuzhong/pr4-product-adapter-feature-cohesion`，
  本地 `master` 与该分支均指向 PR4 完成态 `01b1555`；只存在未跟踪的
  环境/临时目录和文件，这些不属于本任务，必须保留。
- `origin/master` 当前仍指向 PR3 `7f51189`。用户已确认以本地 `01b1555`
  作为 PR5 基线；执行远端 checkout/pull 会回退并丢失 PR4，因此不执行该
  回退操作，只记录本地基线 SHA。
- 当前 `build_agent_composition()` 在
  `lion_code/composition/agent_builder.py` 中先构造
  `api_configured=lambda: ... provider_controller.api_configured` 与
  `child_config=lambda: _child_config(provider_controller, identity_port)`，
  随后才赋值并构造 `ProviderController`。这使 FullProfile 的
  Session/Capability/SubAgent 路径可经 closure 回到 ProviderController。
- `ProviderController` 仍是 ProviderState 的唯一可写 command owner；既有
  Provider switching、thinking switching、child Agent provider inheritance 和
  session restore 行为必须保持。
- PR4 已建立 `CodingSessionBackendAdapter`，但当前
  `build_full_coding_backend()` 仍在 adapter 模块内同时承担 config、bindings、
  profile、AgentComposition、MetaAgent 与 adapter 的产品装配。
- 现有架构契约要求 `build_agent_composition()` 是唯一 Agent Composition Root，
  `AgentRuntime` 不依赖 `ProviderController`，CapabilityRegistry 不是
  service locator，且不保留兼容层。
- 现有 `tests/architecture/test_runtime_ownership.py:213-228` 只用 `vars()` 做
  MinimalProfile 的单层检查；没有递归 `__dict__`/`__slots__`、容器、bound
  method、partial、closure cell 或 visited set 的 reachable graph helper。
- 探索已确认三种 Profile 都可到达
  `AgentRuntime → RuntimeIdentityPort._api_configured → closure cell →
  ProviderController`；FullProfile 另有
  `SessionRuntime → CapabilityRuntime → SubagentFactory._child_config →
  closure cell → ProviderController` 路径。
- `tests/architecture/test_composition_profiles.py:128-289` 已覆盖三 Profile 的
  Capability/Profile 形态，但未覆盖递归引用闭包；新增图门禁应放在
  `test_runtime_ownership.py`，而不是产品代码。

## Requirements

### R1. 关闭 Provider late-bound closure

- 移除所有在 `ProviderController` 构造前捕获未来
  `provider_controller` 的 callback、lambda 或等价 closure。
- 重新确定最小的 Provider configuration read boundary：允许引入真正独立的
  只读 projection/source，但它必须在生命周期上可先于 ProviderController 确定，
  不复制 writable ProviderState，不是 future-controller callback 的包装，也不
  引入 service locator、`bind()` 或 late initialization。
- `AgentRuntime` 不得直接或间接可达 `ProviderController`；
  `RuntimeIdentityPort`、`SubagentFactory` 及 child Agent config 路径不得通过
  closure 或其他引用回到 `ProviderController`。
- `ProviderController` 继续拥有 Provider configuration/thinking command 与
  唯一 writable ProviderState，并继续通过现有窄端口命令 Conversation、Context、
  Session。

### R2. 用 reachable-object-graph 证明 DAG

- 扩展 `tests/architecture/test_runtime_ownership.py` 或其当前对应测试，分别
  构造 `MinimalProfile`、`CodingProfile`、`FullProfile`。
- 图遍历必须覆盖允许的 composition 对象的 `__dict__`/`__slots__`、容器、bound
  method、`functools.partial`（如存在）以及 callable closure cell contents，
  使用 visited set，且不得扫描整个 Python runtime。
- 证明三种 Profile 下 `AgentRuntime` 都不可达 `ProviderController`；在
  FullProfile 下证明 Session/Capability/SubAgent 路径不会回到自身。
- 增加针对 `composition/agent_builder.py` 的静态门禁，禁止未来变量
  `provider_controller` 被 lambda/function closure 捕获。

### R3. 收正 Product Composition Root

- 保留 `lion_code/adapters/coding_session_backend.py` 中的
  `CodingSessionBackendAdapter`，使其只实现 `CodingSessionBackend` protocol
  的产品委托职责。
- 将 `build_full_coding_backend()` 移到 `lion_code/composition/` 下明确的
  product/bootstrap 模块；该 factory 必须继续复用
  `build_agent_composition(FullProfile(...))`，且只建立一条
  Composition → AgentComposition → MetaAgent → Adapter 调用链。
- 同步 CLI、应用和测试 imports；不建立第二个 Agent Composition Root，不把
  Product 逻辑倒灌进 MetaAgent、Runtime、Capability 或 Supervisor。

### R4. 范围约束

本任务不重构 Agent Kernel、AgentHarness loop、Capability SPI、Profile 语义、
Plan/Skill/SubAgent 实现、Session persistence、Context policy、Supervisor、
Trellis 或无关 hooks/benchmark。除上述目标必需外不做 cleanup，不保留旧路径
兼容 alias/fallback。

### R5. 基线、报告与验证

- 实施开始前确认并记录本地最新可用基线 commit SHA `01b1555`；由于远端
  `origin/master` 是旧 PR3，不能用 checkout/pull 将工作区回退。保留工作区中
  不属于本任务的未跟踪内容，并只操作本任务文件。
- 运行 runtime ownership、三 Profile/FullProfile composition、SubAgent/Skill
  child execution、provider/thinking switching、session restore、context
  compaction、Product Adapter、Application、Supervisor 及全量测试。
- 按仓库现有 CI 约定运行 compile、ruff、format、mypy baseline、import-linter、
  radon、vulture、coverage 和 quality baseline；将 focused/scope 结果与既有
  dirty-worktree 或 baseline 噪声分开报告。
- 对用户指定的 residual symbols/paths、late-bound closure、lambda 捕获和
  closure cell → ProviderController 做精确扫描；历史 archive 可排除，当前
  架构测试中的“断言不存在”引用不应误报为生产残留。

## Acceptance Criteria

- [ ] 当前生产代码中不存在捕获未来 `provider_controller` 的 closure、
      `lambda ... provider_controller` 或 closure cell 指向 ProviderController。
- [ ] Minimal/Coding/Full 三种 Profile 的 reachable-object-graph 测试通过；
      `AgentRuntime` 不可达 ProviderController，FullProfile 的
      Session/Capability/SubAgent 路径无回环。
- [ ] Provider configuration writable state 只有 ProviderController 一个 owner，
      既有 provider/thinking/child inheritance/session restore 行为测试通过。
- [ ] `CodingSessionBackendAdapter` 不持有 Product Composition Root；产品 factory
      位于 composition/bootstrap 边界并复用 `build_agent_composition()`，CLI、应用
      与测试调用链全部通过新位置。
- [ ] PR1–PR4 的边界和行为不变量保持；无第二个 composition root、service
      locator、late bind、兼容层或超出范围的架构修改。
- [ ] 指定 residual scan 为零（历史 archive 与“断言不存在”的测试引用按规则
      处理），所有聚焦测试、全量测试与可执行 quality gates 的结果已记录。
- [ ] 最终报告说明改前 hidden cycle、改后完整 DAG、Provider read/write owner、
      reachable graph 结果、Adapter/Composition 边界、residual scan、验证结果，
      并判断 Lion-Code Agent 本体是否可以封板；若可以，说明未来 Memory/MCP/
      Browser/Learning/Autonomy 只能通过哪些 extension boundary 接入，以及
      不得修改哪些 Kernel/Runtime 原则。

## Out of Scope

- PR1–PR4 已完成架构的重新设计或兼容迁移。
- Agent Kernel、Harness loop、Capability SPI、Profile、Session persistence、
  Context policy、Supervisor、Trellis、hooks、benchmark corpus 的独立重构。
- 为未来能力预先新增 Memory/MCP/Browser/Learning/Autonomy 实现。

## Open Questions

无。具体只读 Provider projection 的形态、新 product/bootstrap 文件名和图遍历
helper 的物理位置由现有代码、架构规范和探索结果决定，不改变上述验收标准。
