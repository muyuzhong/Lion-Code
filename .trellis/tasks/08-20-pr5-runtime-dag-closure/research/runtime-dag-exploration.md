# PR5 探索记录：Runtime DAG 与 Product Composition

## 基线

- 当前工作区的 `master` 与 PR4 分支均指向 `01b1555`，即 PR4 完成态。
- `origin/master` 仍指向 PR3 的 `7f51189`；以远端 checkout/pull 替换当前工作区会回退 PR4，因此按用户确认保留本地 `01b1555` 作为 PR5 基线。
- 工作区原有未跟踪项为 `.ci-venv/`、`.pi/`、`.tmp-ci/`、`.zcode/`、`after1.tmp`；它们不属于 PR5，必须保留。

## Provider hidden cycle

当前 [`lion_code/composition/agent_builder.py`](../../../../lion_code/composition/agent_builder.py) 的 `build_agent_composition()` 在 `:259-276` 先声明未来的 `provider_controller`，再创建两个 callback：

```text
AgentRuntime
  -> RuntimeIdentityPort._api_configured
  -> lambda closure cell
  -> ProviderController

FullProfile:
SessionRuntime
  -> CapabilityRuntime
  -> SubagentFactory._child_config
  -> lambda closure cell
  -> ProviderController
```

随后 `ProviderController` 在 `:332-339` 才构造。当前 `ProviderController` 的配置读取实现位于 [`lion_code/runtime/provider.py`](../../../../lion_code/runtime/provider.py) `:162-238`，其中 `api_configured()` 与 `child_api_kwargs()` 都直接读取其 `_state`。

探索确认这不是字段名问题：递归探针沿 `__dict__`、`__slots__`、容器、bound method 与 closure cell 能发现上述路径；现有 `tests/architecture/test_runtime_ownership.py:213-228` 只做 MinimalProfile 的 `vars()` 单层检查，无法发现它。

## Test placement

- 三种 Profile 的构造与形态测试已有 [`tests/architecture/test_composition_profiles.py`](../../../../tests/architecture/test_composition_profiles.py) `:128-289`，但没有递归对象图检查。
- reachable graph helper、closure 访问和 ProviderController 不可达断言应放入 [`tests/architecture/test_runtime_ownership.py`](../../../../tests/architecture/test_runtime_ownership.py)，靠近现有双向引用测试；不放入生产代码。
- helper 必须有 visited set，并只沿 Lion composition graph 的允许模块/容器展开；外部 provider/mock/runtime globals 不展开，避免扫描整个 Python runtime。
- 已有架构聚焦集合在当前基线通过 `66 passed`；这是变更前证据，不代表 PR5 完成。

## Product factory placement

- `CodingSessionBackendAdapter` 位于 [`lion_code/adapters/coding_session_backend.py`](../../../../lion_code/adapters/coding_session_backend.py) `:61`，当前文件还在 `:324-407` 定义 `build_full_coding_backend()`，同时负责 `AgentConfig`、`RuntimeBindings`、`FullProfile`、`build_agent_composition()`、`MetaAgent` 和 Adapter 装配。
- CLI 在 [`lion_code/__main__.py`](../../../../lion_code/__main__.py) `:11-14`、`:312` 从 adapter 模块导入并调用 factory；多处测试也从该模块导入 factory。
- `tests/architecture/_boundaries.py` 的 Composition contract 只禁止 Application、MetaAgent、Supervisor、TUI，不禁止 Composition import Adapter，因此 `lion_code/composition/full_product.py` 可以承载 product bootstrap，并导入 `CodingSessionBackendAdapter`。
- 为避免 package `composition/__init__.py` 与 `meta_agent` 的循环导入，factory 迁移后由调用方显式从 `lion_code.composition.full_product` 导入；`composition/__init__.py` 不再为了兼容重新导出它。

## 设计方向

在 `lion_code/runtime/provider.py` 增加稳定的 `ProviderConfigurationProjection`：它在 ProviderController 之前用初始 `ProviderState` 与初始 provider-ready 标志构造，只保存当前 `ProviderState` 的共享引用并提供 `api_configured`/child API read projection。ProviderController 仍是唯一 ProviderState command owner；每次成功提交 target state 后只同步 projection 的 state 引用。Projection 不持有 ProviderController，RuntimeIdentityPort 与 SubagentFactory 只触达 projection，因而对象图可拓扑排序且不复制第二份 writable ProviderState。
