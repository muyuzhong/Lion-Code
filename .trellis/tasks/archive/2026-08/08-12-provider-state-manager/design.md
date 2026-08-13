# Provider 配置与 Thinking 生命周期设计

## 1. 模块与所有权

新增 `lion_code/provider_manager.py`，删除迁移后的 `lion_code/agent_lifecycle.py`。

```text
Agent facade / composition root
        │  ProviderView + commands
        ▼
ProviderManager ── owns ── ProviderState
        │
        ├─ ProviderRuntimePort       -> existing AgentRuntimeCoordinator/Core Runtime
        ├─ ModelContextControl        -> compactor + model-limit cache
        ├─ MemoryQuerySink            -> existing SessionMemoryCoordinator entry point
        ├─ ConfigurationRecorder      -> scheduled SessionRecorder writes
        └─ provider_factory Callable  -> Agent's dynamic create_provider seam
```

`ProviderManager` 不 import `Agent`，也不持有 `Agent`、`LionAgentRuntime` 或另一份
conversation history。活跃 Provider 仍只存放在既有 `LionAgentRuntime`；Manager 只保存
配置源状态，并为 replacement 构建临时 Provider/派生服务。

## 2. State / View

```python
ProviderKind = Literal["anthropic", "openai-compatible"]

@dataclass(slots=True)
class ProviderState:
    model: str
    provider_kind: ProviderKind
    api_key: str
    openai_base_url: str | None
    anthropic_base_url: str | None
    thinking_enabled: bool
    thinking_level: ThinkingLevel

@dataclass(frozen=True, slots=True)
class ProviderView:
    model: str
    provider_kind: ProviderKind
    thinking_enabled: bool
    thinking_level: ThinkingLevel
```

`ProviderView` 不暴露凭证和可写 State；`provider_name`、`use_openai`、legacy
`thinking_mode`、`api_configured` 和 active `base_url` 都是 Manager/View 的派生读取，
不另存一份。Manager 不公开 `ProviderState` 引用；唯一写入点是 Manager 内部的目标
State commit。

`thinking_enabled` 保留布尔 API 的兼容来源，`thinking_level` 保留 Core/Tau 档位来源。
`set_thinking(bool)` 继续返回按当前 model 能力解析的 legacy mode 并写入既有 thinking
记录；`set_thinking_level()` / restore 使用归一化后的六档词汇并按现有行为重建 Provider。
不在本切片改变已有 Thinking 词汇或 Session JSONL schema。

## 3. 窄依赖

Provider Manager 只声明以下小 Protocol：

```python
class ProviderRuntimePort(Protocol):
    @property
    def is_running(self) -> bool: ...
    def replace_provider(self, provider: ModelProvider) -> ModelProvider: ...
    def set_model(self, model: str) -> None: ...

class ModelContextControl(Protocol):
    def replace_context_compactor(self, compactor: ContextCompactor) -> None: ...
    def invalidate_model_limit_cache(self, model: str) -> None: ...

class MemoryQuerySink(Protocol):
    def set_query_service(self, service: ProviderTextQueryService) -> None: ...

class ConfigurationRecorder(Protocol):
    def record_configuration_change(
        self, previous: ProviderView, current: ProviderView
    ) -> None: ...
```

`ConfigurationRecorder` 的具体适配器负责把 model/thinking entry 写入已有异步后台队列；
Provider kind/credential 变化只作为一次配置变化通知，不新增 Session entry 类型。必要
的初始组装和 recorder scheduling 使用小型 Callable，不创建包含 Agent 字段的替代 Host。

## 4. Command 与事务

### configure

1. 读取当前 View/State，拒绝运行中配置。
2. 解析目标 model、Provider kind、key、两个 base URL，按当前环境变量/default 行为
   填充缺省值；计算是否需要 replacement。model-only 仍只调用 `set_model`。
3. 若需要 replacement，先调用注入的 `provider_factory`，再创建对应
   `ProviderContextCompactor` 与 `ProviderTextQueryService`；任何异常立即退出。
4. replacement 成功后调用 `replace_provider`，再调用 `set_model`。
5. 将目标值一次性 commit 到 Manager 的 `ProviderState`。
6. 调用 `replace_context_compactor`、`invalidate_model_limit_cache` 和
   `set_query_service`。
7. 通知 `ConfigurationRecorder`。
8. 最后通过 scheduler 异步关闭 `replace_provider` 返回的旧 Provider。

所有可失败的 Provider/派生服务构建发生在 Runtime/State mutation 之前；失败路径不
触碰旧 Provider、State、history、compactor、Memory query 或 recorder。

### Thinking commands

- `set_thinking(enabled)` 在 Manager 内更新 `thinking_enabled`，用 model/provider kind
  解析 legacy 返回值，并经 recorder 持久化；不把 `_thinking_mode` 重新引入 State。
- `set_thinking_level(level)` 先 normalize；未变化直接返回。变化时按同一 replacement
  事务用当前 credential/base 构建 Provider，成功后 commit level、刷新 compactor/query/
  cache、记录 thinking entry、异步关闭旧 Provider。
- `cycle_thinking_level()` 只消费 Manager 的 View 和 `provider_thinking_levels()`，再
  委托 `set_thinking_level()`。
- `restore_configuration(model, thinking_level)` 是不记录历史的明确恢复命令。它从持久化
  model 和 `coerce_thinking_level()` 得到目标；model-only 使用 runtime `set_model`，
  Thinking 变化使用 replacement 事务。失败时原配置和 Runtime 不变。
- `build_provider(level=None)` 只按当前 State 或指定 normalized level 调用 factory，
  不安装 Provider，不产生第二个 active Runtime。

## 5. Agent / Runtime / Session wiring

- `Agent.__init__` 只在组合根创建初始 `ProviderState`/Manager，并把动态
  `self._create_provider` 作为 factory Callable 注入；Manager 构建初始 Provider 后，
  仍交给唯一 `AgentRuntimeCoordinator`。
- Runtime/context/memory 的具体实现通过窄适配器绑定到已经存在的 coordinator 和
  SessionMemoryCoordinator；Manager 不接收 Agent，不读取 Agent 私有字段。
- Agent 保留 `model`、`provider_name`、`api_configured`、配置方法和 Thinking API，全部
  从 Manager 的 View/command delegate。`_child_api_kwargs()` 改为请求 Manager 的配置
  projection，不直接读 credential mirror。
- `RuntimeIdentityHost` 只消费 ProviderView 中需要的 model/thinking projection；
  `effective_window` 仍由 Context/limits runtime 派生，不进入 ProviderState。
- `SessionLifecycle.restore_core_session()` 读取 JSONL 后调用 coordinator 暴露的
  ProviderManager restore command，再处理 canonical messages、Session identity、
  observer 和 usage reset；不再写 `identity.model` 或 Thinking private field。

## 6. Compatibility / rollback

- `Agent._create_provider()` 继续在 `lion_code.agent` 模块内动态解析
  `create_provider`；Manager 只接收 Callable，因此已有 patch 覆盖初始构造、API 切换、
  Thinking rebuild 和 child construction。
- `LionAgentRuntime` 实例、Harness queues、messages 和 JSONL writer 不变；替换只调用
  既有 `replace_provider`。
- 若事务顺序、restore 或 patch seam 回归，回滚本任务的 ProviderManager/Agent/Runtime/
  Session changes；不触碰 PR1、Memory Host、Capability PromptLayer 或 AgentBuilder。

## 7. Test design

- 新增 ProviderManager unit tests：State/View projection、目标配置解析、busy rejection、
  replacement failure atomicity、command order、model-only、Thinking、restore、record
  and async close。
- 扩展 integration tests：hot swap、protocol switch、history preservation、compactor /
  Memory query refresh、model-limit invalidation、old provider close、thinking persistence、
  restore and child credential inheritance。
- 扩展 `tests/architecture/test_runtime_boundaries.py`：Manager import/constructor
  isolation、State writable-owner scan、Agent mirror scan、restore private-write scan。
