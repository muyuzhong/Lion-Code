# PR4 — Product Adapter / Feature Cohesion

## 背景

PR1（Runtime Boundary）、PR2（Profile/Config/RuntimeBindings 三轴分离）、PR3（Runtime 所有权 + Provider DAG）已全部合并。当前遗留两个结构性问题：

1. `lion_code/agent.py` 的 `class Agent(MetaAgent)` 名为 Agent、实为 FullProfile 产品适配器，继承关系是错误表达——项目唯一通用 Agent 概念是 `MetaAgent → AgentRuntime → Kernel`，产品需求应由组合 Adapter 实现。
2. Plan / Skill / SubAgent 三个 Feature 的实现物理散落在 package root（`plan_runtime.py`、`skill_runtime.py`、`skills.py`、`subagent.py`、`subagent_factory.py`、`subagent_runtime.py`）与 `capabilities/plan.py` 等处，与 Capability 架构不一致。

本 PR 是 Agent 本体架构封板 PR。

## 需求

### R1 删除 Agent 继承，建立 Product Adapter

- 新建 `lion_code/adapters/coding_session_backend.py`：
  - `CodingSessionBackendAdapter`：通过**组合/委托**实现 `lion_code.application.ports.CodingSessionBackend` protocol（结构化实现，不显式继承 Protocol、不继承 MetaAgent）。
  - 构造签名形如 `__init__(self, *, agent: MetaAgent, plan, confirmation, notices, status_sink, terminal_output_sink, session_repository, cwd)`。
  - 迁入产品职责：session listing / restore_latest / legacy session 迁移、Plan approval/toggle、terminal 交互回调（set_terminal_output）、confirmation、notices、cost 投影（show_cost）、应用便利 API（clear_history、is_processing、abort 等）。
- 提供 FullProfile 产品的公共构造入口（factory），内部走 `build_agent_composition(FullProfile, ...)` → MetaAgent → Adapter，替换 `__main__.py` 中的 `Agent(...)`。
- MetaAgent 补齐 generic 缺口（只加通用对话/Provider 投影，不加产品职责）：`queue_snapshot()`、`compact_for_overflow()`、`is_running`、`api_configured`、`provider_name`。
- **删除** `lion_code/agent.py` 与 `class Agent`。不保留 LegacyAgent / alias / deprecated wrapper。
- 测试中 `new Agent()` 全部迁移到真实公共构造路径。

### R2 Feature Cohesion

目标结构（具体归属按真实职责）：

```
capabilities/
├── types.py        # generic Capability SPI（不知道 plan/skill/subagent）
├── registry.py
├── runtime.py
├── plan/           # capability.py + runtime.py
├── skill/          # capability.py + runtime.py + discovery.py
└── subagent/       # capability.py + runtime.py + factory.py + types.py
```

移动映射：

| 旧路径 | 新路径 |
|---|---|
| `lion_code/plan_runtime.py` | `capabilities/plan/runtime.py` |
| `lion_code/capabilities/plan.py` | `capabilities/plan/capability.py` |
| `lion_code/skill_runtime.py` | `capabilities/skill/runtime.py` |
| `lion_code/capabilities/skill.py` | `capabilities/skill/capability.py` |
| `lion_code/skills.py` | `capabilities/skill/discovery.py` |
| `lion_code/capabilities/subagent.py` | `capabilities/subagent/capability.py` |
| `lion_code/subagent_runtime.py` | `capabilities/subagent/runtime.py` |
| `lion_code/subagent_factory.py` | `capabilities/subagent/factory.py` |
| `lion_code/subagent.py` | `capabilities/subagent/types.py` |

- 不留旧路径兼容 shim（项目原则：无向后兼容）。
- generic SPI（types/registry/runtime）不得 import feature 实现；SPI 内不得出现 if plan/skill/subagent 分支。
- Feature 构造分支仍只在 `composition/agent_builder.py`（Composition Root）。

### R3 Profile preset 语义保持

PR2 结果不变：MinimalProfile → Kernel+minimal Runtime；CodingProfile → Minimal+coding tooling；FullProfile → Coding+Plan+Skill+SubAgent。三者是 composition presets，不是 Agent/Runtime 子类型；extension_specs 与三者正交。

### R4 残留清理

全仓扫描（生产代码、测试、spec、docs，不含 `.trellis/tasks/archive/` 历史档案）：`class Agent`、`from lion_code.agent`、`plan_runtime`/`skill_runtime`/`subagent_runtime`/`subagent_factory` 旧模块路径、`AgentDependencies`、`DeferredProviderRuntimePort`、`DeferredModelContextControl`、`DeferredBackgroundScheduler`、`AgentRuntimeCoordinator`、`SessionLifecycle`。被本轮架构替代的 symbol 不得作为当前架构出现（架构测试中"断言不存在"的引用除外）。

### R5 Architecture tests

新增/更新架构测试证明：

1. package root（`lion_code.__all__`）没有 `Agent`。
2. `CodingSessionBackendAdapter` 结构化满足 `CodingSessionBackend`（runtime checkable 或逐 port 委托断言）。
3. Product Adapter 不继承 MetaAgent（MRO 断言）。
4. MetaAgent 无 Plan/UI/legacy-session 产品职责（AST：方法名黑名单）。
5. generic Capability SPI（types/registry/runtime）不 import plan/skill/subagent 实现。
6. 三个 feature package 各自内聚全部 feature-specific 实现（文件树断言）。
7. Application/TUI 不直接依赖 Harness（沿用现有门禁）。
8. Supervisor 不 import Product Adapter。
9. Minimal/Coding/Full 构造出相同 MetaAgent 类型 + 相同 Runtime 类型组合（沿用 test_composition_profiles 模式）。

## 验收标准

- [ ] `lion_code/agent.py` 删除，`grep -rn "class Agent(" lion_code` 无结果。
- [ ] `__main__.py` 调用链：factory → CodingSessionBackendAdapter → MetaAgent，无 Agent 继承。
- [ ] Feature 文件全部迁移，旧路径文件删除，全仓无旧路径 import。
- [ ] 9 条架构测试全部落地且通过。
- [ ] 全量 unittest + CI quality gates（ruff/mypy/radon/vulture 对基线）通过。
- [ ] 输出：调用链前后对比、最终目录树、Feature 移动表、公共 API、依赖图、residual scan、测试结果。
- [ ] 结论：Agent 本体架构是否具备封板条件 + Memory/MCP/Autonomy/Learning 的接入边界说明。

## 约束

- 分层边界由 `tests/architecture/*` + import-linter 强制；改动同步架构测试期望与 `.trellis/spec/backend/*.md`。
- 每个 commit 中文描述、单一职责。
- 不为兼容留任何 fallback（项目原则 1）。
