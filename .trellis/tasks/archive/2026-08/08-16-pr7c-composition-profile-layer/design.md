# PR7c Composition Profile Layer — Design

## 1. First-principles boundary

目标不是给 Agent 增加开关，而是把已经存在的 Bare graph 组合成三个可辨认产品。保留一个
`build_agent_composition(profile)`：Profile 提供不可变选择，builder 一次性创建 graph；Profile 不拥有
lifecycle、不解析服务、不暴露 runtime lookup。

## 2. Verified input boundary

```text
build_meta_agent(provider, tools, ...)
  -> caller-owned ToolRegistry
  -> empty CapabilityRegistry
  -> shared AgentRuntimeCoordinator / Kernel / Harness
  -> MetaAgent
```

PR7b 后 Full Product 只剩 Skill/SubAgent/Plan/Memory，但仍由 `PRODUCT_CAPABILITIES` 与 builder 内的
默认 tools/policy/prompt 分散选择。PR7c 只收口这些真实选择，不修改 Bare runtime 控制流。

## 3. Profile data

`composition/profiles.py` 定义：

- `ProductFacadeKind`: `META` / `FULL`，只描述 facade，不编码 Feature。
- `SkillComposition`: Coding 可选 Skill 的存在值，不使用 `skill=True`。
- `MinimalProfile`: config、dependencies、caller tools、permission strategy、neutral prompt、META facade；
  内置 Capability 固定为空。
- `CodingProfile`: config、dependencies、command backend、permission strategy、extra tools、coding prompt、
  optional SkillComposition、META facade；Profile 类型固定选择 Coding tool suite。
- `FullProfile`: Coding 构造输入、default SkillComposition、extension specs、FULL facade；Profile 类型固定
  构造 Memory/Plan/SubAgent。

三种类型均为 frozen/slots dataclass，不定义 `build/get/resolve`、状态镜像或生命周期方法。公共 Profile
不接受 feature-name set；具体 Feature 名和构造 branch 只存在于 Composition Root。

`AgentConfig` 删除 prompt/tools 等组合字段，只保留通用运行值；`AgentDependencies` 只保留外部对象与
工厂。prompt、tools、permission strategy、backend、extensions 与 facade 都只有 Profile 一个来源。

## 4. One composition entry

```text
Profile value
  -> private _ProfileSelection
  -> Foundation + Provider graph
  -> Capability graph
  -> Tooling + PromptComposer
  -> AgentRuntimeCoordinator + Session graph
  -> AgentComposition
  -> selected product facade
```

`_ProfileSelection` 是 builder 内的一次性值，不导出、不做 registry lookup。Feature branching 只存在于
Profile normalization/Capability helpers；Kernel/Harness 仍只接收 ToolRuntime、prompt callback、
provider、context 与 lifecycle ports。

## 5. Tools and command backend

`tooling/execution.py` 提供最窄契约：

```python
class CommandExecutionBackend(Protocol):
    def run(self, command: str, *, timeout_ms: float) -> str: ...
```

`LocalCommandExecutionBackend` 封装当前 `subprocess.run(shell=True, capture_output=True, text=True)` 及既有
超时/错误文本语义。`create_builtin_tools()` 显式接收 backend 并绑定 `run_shell`；其他工具保持不变。

Minimal 只注册 caller tools。Coding/Full 注册 backend-bound builtin Coding tools、`tool_search` 与 Profile
extra tools。动态 prompt 不为收集 deferred names 而偷偷创建默认 backend。

## 6. Permission strategy

`ToolPermissionStrategy` 只声明 `check_hard_boundaries()` 与 `check()`；现有 `PermissionPolicy` 结构化实现
该契约。Profile 保存 strategy 实例，Composition Root 原样交给 PermissionMiddleware；PermissionMode
和 confirmation state 仍由现有通用 runtime owners 管理。

## 7. Facades and child graph

- `build_meta_agent()` 创建 MinimalProfile，返回 MetaAgent。
- `build_coding_agent()` 创建 CodingProfile，返回 MetaAgent；MetaAgent 增加通用 `run_once()` 以满足
  `_ChildRuntime`，不增加 Feature facade。
- Full `Agent` 以 FullProfile 构造并绑定现有 Plan/Skill/SubAgent/Memory facade 字段。
- `SubagentFactory` 使用 CodingProfile/build_coding_agent，只传递 selected registry、Provider snapshot、
  permission strategy 与 prompt，不递归创建 Full-only Capability。

facade 构造后只保存 AgentComposition 中的明确 owners，不保存 Profile、builder 或 service registry。

## 8. Expected object graphs

```text
MinimalProfile -> MetaAgent
  ProviderManager + caller ToolRegistry + empty CapabilityRegistry
  + PermissionStrategy + neutral PromptComposer + Runtime/Session/Usage

CodingProfile -> MetaAgent
  Minimal foundation + CodingTools(backend-bound) + tool_search
  + Coding PermissionStrategy + Coding Prompt
  + optional Skill -> SkillRuntime + hidden child machinery

FullProfile -> Agent
  Coding graph + Memory + Plan + SubAgent + Skill + extra CapabilitySpecs
  + Capability prompt/session/resource contributions
  - MCP / Autonomy / Dream / Learning
```

测试用 fake Provider/backend/strategy 构造真实 graph，并通过 registry names、tool execution、object
identity、prompt rendering 与 facade type 验证，而不是只断言常量。

## 9. Compatibility and rollback

不保留旧 `capabilities=`、`PRODUCT_CAPABILITIES` 或 Meta/Coding 隐式默认工具入口。现有 `Agent(...)`
Provider、budget、permission 和 dependency injection 参数映射到 FullProfile；prompt/tools 映射到 Profile
字段。PR7c 不新增依赖，整体回滚恢复 PR7b 的 capability-only Product 选择。
