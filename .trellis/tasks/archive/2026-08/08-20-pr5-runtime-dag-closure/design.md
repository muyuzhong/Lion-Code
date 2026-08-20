# PR5 技术设计 — Runtime DAG Closure 与 Product Composition

## 1. 不变量与边界

PR5 只收口 PR3 的 Provider read dependency 和 PR4 的 product factory 归属，不
重新设计 PR1–PR4 的 Runtime owner、Profile、Capability SPI、Session 或
Supervisor。必须保持：

- `ProviderController` 是 Provider configuration/thinking 的 command owner，
  `ProviderState` 仍只有一个权威可写 owner。
- `AgentRuntime` 只编排 Conversation、Session、Context 三个 Runtime owner，
  不直接或间接持有 `ProviderController`。
- `CapabilityRegistry` 仍只是 immutable contributions 的聚合器，不成为
  service locator。
- child Agent 仍继承调用时的当前 Provider configuration，Provider switching、
  thinking switching、session restore 的行为与记录顺序不变。
- `CodingSessionBackendAdapter` 仍是 Product Adapter；Product composition
  只存在一个 root，并复用 `build_agent_composition()`。

## 2. Provider configuration read projection

### 2.1 结构

在 `lion_code/runtime/provider.py` 增加
`ProviderConfigurationProjection`，它不是 ProviderController 的 port、callback
或 service locator，而是由 Composition Root 在 controller 之前构造的稳定 read
source：

```text
ProviderState ───────────────┐
                             ├─ ProviderConfigurationProjection
initial provider-ready ─────┘          ↑ read only
                                       ├─ RuntimeIdentityPort
                                       └─ SubagentFactory

ProviderController ──(成功提交后同步 projection state reference)
```

Projection 的约束：

1. 不存储 `ProviderController` 引用，也不通过 closure、bound callback 或
   `functools.partial` 回指 controller。
2. 不复制 ProviderState 字段；它只保存当前 authoritative `ProviderState` 的
   引用，并提供 `api_configured` 与 child API kwargs 的派生只读视图。
3. 初始 provider 已由 Composition Root 决定时，保存既有 provider-ready 标志，
   保持当前注入 provider 的测试/运行语义。
4. 只允许 ProviderController 在 target state 已成功应用后同步 projection 的
   state reference；projection 不向其他对象暴露 Provider configuration command。
5. ProviderController 的 provider 构造失败或 Conversation 回滚时不得提前
   同步 projection，避免读投影领先 authoritative state。

### 2.2 构造顺序

`build_agent_composition()` 调整为：

```text
foundation → ProviderState → initial Provider
          → ProviderConfigurationProjection
          → RuntimeIdentityPort
          → Capability graph / SubagentFactory
          → tooling / ContextRuntime / ConversationRuntime / SessionRuntime
          → AgentRuntime
          → ProviderController
```

`RuntimeIdentityPort` 使用 projection 的 bound read method；SubagentFactory 的
child-config callable 使用 projection + identity port 的已构造对象（推荐
`functools.partial`，不捕获未来局部变量）。`provider_controller` 不再在
controller 构造前声明，也不出现在任何 builder lambda/function closure 中。

`ProviderController` 增加 projection 的窄更新依赖，并在 `_apply_target_state()`
成功完成 Conversation provider/model 提交后更新 projection；现有
`get_api_config()`、`view`、Provider command API 仍从 authoritative `_state`
读取，避免将 command owner 改成 projection。

## 3. Reachable object graph architecture gate

在 `tests/architecture/test_runtime_ownership.py` 增加测试专用 traversal：

- 入口是 `build_agent_composition()` 返回的三个 Profile 图：
  `MinimalProfile`、`CodingProfile`、`FullProfile`。
- 展开 `__dict__` 与所有 MRO `__slots__`，以及 list/tuple/set/frozenset/dict。
- 展开 bound method 的 `__self__` 与函数 closure 的 `cell_contents`；展开
  `functools.partial` 的 func/args/keywords。
- 用 `id()` visited set 保存路径，跳过 primitive、module、type、外部
  provider/mock 与 Python globals，只沿 `lion_code` 对象和容器进入，输出失败
  路径便于定位。
- 不读取 descriptor/property，不执行任意 callable；只检查已经存在的引用。

断言矩阵：

| 入口 | 禁止到达 | 目的 |
|---|---|---|
| `composition.runtime.agent` | `composition.runtime.provider_controller` | AgentRuntime 无 Provider 回边 |
| `composition.runtime.session` | ProviderController | Full Session → Capability → SubAgent 不回 controller |
| `composition.capabilities.runtime` | ProviderController | Capability graph 不持有 Provider command owner |
| `composition.capabilities.subagent_factory`（Full） | ProviderController | child config read source 独立 |

另外保留既有 ProviderController 不引用 AgentRuntime 的静态/行为检查，并增加
AST 门禁：任何 lambda 或嵌套 function closure 不得以 load 形式引用
`provider_controller`；module-level helper 若需要 provider 输入必须改为
projection 参数，不能保留未来 controller 参数。

## 4. Product composition relocation

新建 `lion_code/composition/full_product.py`，只放 Full product bootstrap：

```text
__main__/tests
    ↓ import build_full_coding_backend
composition.full_product
    ├─ AgentConfig / RuntimeBindings / FullProfile
    ├─ build_agent_composition(...)
    ├─ MetaAgent(composition.runtime...)
    └─ CodingSessionBackendAdapter(...)
```

从 `adapters/coding_session_backend.py` 移除 factory、factory 私有默认绑定及
其 product bootstrap imports；Adapter 文件只保留 Adapter class、它需要的
product delegation imports 和 `__all__ = ["CodingSessionBackendAdapter"]`。

调用方与 monkeypatch seam 统一改为：

- `CodingSessionBackendAdapter` 从 `lion_code.adapters.coding_session_backend`
  导入。
- `build_full_coding_backend` 从 `lion_code.composition.full_product` 导入。
- factory 内的 provider seam 改 patch `lion_code.composition.full_product`，
  不保留 adapter 模块的兼容别名。

不将 factory 重新导出到 `composition/__init__.py`，避免 package 初始化时
引入 Adapter → MetaAgent → Composition 的循环；显式模块路径就是新的
bootstrap boundary。

## 5. Spec、残留与报告

同步 `four-layer-ownership.md`、`runtime-boundaries.md`、
`directory-structure.md`，说明 projection 是 Runtime read boundary、factory
属于 Composition bootstrap。历史 `.trellis/tasks/archive/` 不做机械改写。

精确扫描当前 production/docs/tests（排除 archive、cache，以及测试中用于
断言缺失的字符串）中的用户指定 residual symbols/path 和 provider closure。
报告必须分离：

1. PR5 前的两个 hidden cycle 路径；
2. PR5 后的 DAG 与 read/write owner；
3. FullProfile reachable graph 结果；
4. Adapter/Composition 边界与调用链；
5. residual scan；
6. focused/full tests 与 quality baseline 结果；
7. 封板判断和未来能力的 extension boundary。

## 6. 风险与回滚

- Projection 同步时机错误会造成 child Agent 读取旧/未来配置；先构造目标
  provider 并完成 Conversation 提交，再同步 projection，并增加 switching/
  restore/child inheritance 测试。
- 迁移 factory 的 imports 可能造成 Composition/Adapter 循环；保持 factory
  只在 `composition.full_product`，不从 `composition.__init__` 自动导出。
- reachable traversal 过宽会进入第三方对象或 globals；模块白名单和 visited
  set 是测试稳定性约束。
- 每个独立改动使用中文 commit 描述；若语义不正确，回滚点依次是 projection、
  graph test、factory move、spec/gate。
