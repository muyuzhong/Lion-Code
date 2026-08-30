# 技术设计：Provider readiness 单一投影

## Planning basis

本设计基于 `sol / high` 规划研究 `research/provider-readiness-minimal-design.md`，并以当前 Lion checkout、架构规范和 Maka 的 `connection-readiness` 作为证据。实现阶段使用 `luna / max`，只落地一个候选改进点。

## Boundary and ownership

`ProviderController` 仍是 Provider 配置与 Thinking 状态的唯一写 owner。`ProviderConfigurationProjection` 仍是 controller-free 的只读边界，只持有 authoritative `ProviderState` 引用及显式 Provider binding 的 ready 事实；它不持有 Controller、不写持久化、不缓存失败。

所有读取面沿单向路径消费同一个 snapshot：

```text
ProviderController / concrete binding
        -> ProviderConfigurationProjection.readiness()
        -> RuntimeIdentityPort / AgentRuntime
        -> ProviderController / MetaAgent / Application
        -> /api/status (api_configured + provider_blocker_code)
        -> Desktop strict ServerStatus decoder
```

TUI 只继续消费 Application 的兼容 bool，不新增 blocker 分支。`AssistantMessage`、WebSocket 和 JSONL 不承载 blocker code。

## Contract shape

在 `lion_code/runtime/provider.py` 定义最小不可变类型：

```python
ProviderReadinessBlockerCode = Literal["provider_configuration_required"]

@dataclass(frozen=True, slots=True)
class ProviderReadiness:
    ready: bool
    blocker_code: ProviderReadinessBlockerCode | None
```

`ProviderConfigurationProjection.readiness()` 是唯一判定点：

- 显式注入 concrete Provider：`ready=True`, `blocker_code=None`；
- 现有同步配置规则满足：`ready=True`, `blocker_code=None`；
- 其余当前可观察配置：`ready=False`, `blocker_code="provider_configuration_required"`。

保留 `is_api_configured()`，但只返回 `readiness().ready`。`ProviderController.api_configured` 只委托 projection；如需公开 code，新增只读 `provider_readiness` 属性，不增加写能力。Runtime/Application 先读取完整 snapshot，再派生兼容 bool，避免一次 status 读跨过配置提交造成 bool/code 撕裂。

## Data flow and layer changes

1. Composition 继续在 Controller 前创建 projection；`agent_builder.py` 只把 projection 的 readiness callback 接入既有 `RuntimeIdentityPort`，不建立 Runtime → Controller 反向边。
2. `AgentRuntime.chat` 在发送 gate 读取一次 readiness。blocked 时沿用现有 canonical assistant error 和零 Provider 请求路径；不把 code 加入 Core message。
3. `ProviderController`、`MetaAgent`、`CodingSessionBackendAdapter`、`SettingsPort` 和 `LionCodingSession` 的只读读取统一委托 snapshot。必要的 public surface 变化只增加 `provider_readiness` 读属性，保留 `api_configured`。
4. `/api/status` 从 session 取得一次 readiness，序列化 `api_configured=ready` 和 `provider_blocker_code=blocker_code`。模型使用 nullable literal，禁止任意字符串。
5. Desktop `backend.ts` 将 `provider_blocker_code` 加入 `ServerStatus` 与 `isServerStatus` 严格 predicate；`WorkspaceShell.tsx` 不读取该字段，现有 bool 驱动行为不变。

## Compatibility

- Python、Application 和 REST 保留 `api_configured: bool`，并保持 required。
- REST 新增 required nullable `provider_blocker_code`，因为 sidecar 与 Desktop 同版本交付；不做 optional fallback 或字符串推断。
- 现有“API 未配置” canonical 文案、TUI `/model` 路由、首跑设置弹窗、Provider 配置写入和失败回滚不变。
- 首版不将 blocker code 写入 canonical message、session JSONL、WebSocket event 或 Provider 配置持久化。
- 不新增 Provider catalog、网络探测、异步 credential state 或通用 Resolver/Manager。

## Failure and transaction behavior

`ProviderController._apply_target_state()` 的现有顺序保持：先构建/替换，成功后提交 `_state` 并 `_sync()` projection；任一构建或替换失败时恢复旧 Provider，readiness 不前移。若 REST 配置写盘失败，沿用现有补偿回滚，不能留下新 readiness 与旧磁盘状态不一致。

Readiness 是当前同步配置事实，不记录最近一次失败。缺 key 与缺 OpenAI base URL 首版共享一个修复 code；空 model、未知 model、网络失败和 workspace 状态不属于本次 Provider readiness。

## Testing strategy

以现有测试边界为主，不新增全局测试基础设施：

- Projection/Controller：truth table、显式 Provider、成功同步、factory/replace 失败保持旧 snapshot。
- Runtime/MetaAgent：blocked 不调用 Provider；显式 Provider 无 key 可发送；公共 bool 与 readiness 一致。
- Application/REST：一次 snapshot 同时投影 bool/code；合法组合和敏感信息不泄漏。
- Desktop：strict decoder 接受两个合法组合，拒绝缺字段、未知 code、矛盾组合；现有 UI bool 行为保持。
- Architecture：继续证明 Runtime 不可达 Controller，projection callback 不反向持有 Controller。

## Rollback shape

若定向验证显示现有 sidecar/client 以外还有未覆盖的 status 消费者，先撤回新增 REST 字段及 Desktop decoder 变更，保留规划研究，不扩大兼容层。代码回滚点集中在 Provider projection、status model/route、Application port 和 Desktop decoder；不触碰历史记录、WS schema 或 Provider factory。

## Explicit non-goals

本次不实现 Maka 的 task-submission readiness，不引入四态 admission，不改 TUI/UI 文案，不改 `AssistantMessage`/WS/JSONL，不做跨进程锁、健康探测、模型 catalog、通用状态 Manager 或第二真值源。
