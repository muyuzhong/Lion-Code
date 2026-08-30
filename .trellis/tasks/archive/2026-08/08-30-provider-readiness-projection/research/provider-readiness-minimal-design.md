# Research: Provider readiness 单一投影与最小稳定 blocker code

- Query: 在既有 `ProviderConfigurationProjection` / `ProviderController` 边界内，怎样消除 Runtime 与产品面的 readiness 分裂，保留 `api_configured` 兼容字段，并决定首版是否进入 REST、TUI、Desktop。
- Scope: mixed（Lion 当前实现、测试与 specs；Maka 当前 CodeGraph/源码作为对照，不做互联网检索）
- Date: 2026-08-30

## Findings

### 唯一推荐

首版只做一个 **Provider 配置 readiness 投影**，不要做 Maka 式 task-submission readiness 聚合：

```python
ProviderReadinessBlockerCode = Literal["provider_configuration_required"]

@dataclass(frozen=True, slots=True)
class ProviderReadiness:
    ready: bool
    blocker_code: ProviderReadinessBlockerCode | None
```

`ProviderConfigurationProjection.readiness()` 是唯一判定点；返回值必须满足：

- `ready=True` 时 `blocker_code is None`；
- `ready=False` 时 `blocker_code == "provider_configuration_required"`；
- 当前存在显式注入的 concrete Provider binding 时保持 ready；
- 否则沿用现有配置判定：有非空 API key，且 Anthropic 或 OpenAI-compatible 有 base URL，才是 ready；
- `is_api_configured()`、`ProviderController.api_configured`、`MetaAgent.api_configured`、Application `api_configured` 和 REST `api_configured` 都只能由同一个 `ProviderReadiness.ready` 派生，禁止再写第二套布尔公式。

首版 blocker 只有一个。缺 key 与缺 OpenAI base URL 当前都进入同一个 Provider 设置修复面；拆成两个 code 不会改变任何调用方动作，反而会过早冻结分类。`provider_configuration_required` 描述可执行修复方向，也避免把稳定协议绑死在环境变量名或某个 Provider 的 credential 术语上。

首版不把空 model 纳入 readiness。当前产品路径有默认 model，TUI 对输入做 `strip()`，REST 配置采用保留当前 model 的局部合并；`known_models` 又不是权威目录。若要拒绝空白 model，应在配置写入口做独立输入校验并给 422，而不是把输入校验、模型可用性与 Provider readiness 混成一个新 code。这个选择保持 `api_configured` 的既有可观察语义完全不变。

### 为什么当前确实存在分裂

- Runtime 读取 `ProviderConfigurationProjection.is_api_configured()`；该判定把 `_provider_ready`（显式注入 concrete Provider）视为 ready：`lion_code/runtime/provider.py:40-60`。
- 产品面 `MetaAgent.api_configured` 经过 `ProviderController.api_configured`；Controller 在 `lion_code/runtime/provider.py:249-257` 重新实现凭证公式，但遗漏 `_provider_ready`。
- Composition 明确在 Controller 之前创建 projection，并把 projection 回调交给 Runtime：`lion_code/composition/agent_builder.py:275-293`；因此“注入 Provider、没有 key”的 Agent 能运行，但产品状态会报告未配置。现有 Supervisor profile 测试正以无 key 的 `ProviderBindings(provider=provider)` 成功执行：`tests/architecture/test_composition_profiles.py:527-550`，却没有断言产品 readiness。
- 这不是 UI 缓存问题，而是两个读取面各算一次同一事实。修复点必须是投影与 Controller 的读取关系，不能在 REST/TUI/Desktop 各自补判断。

### 推荐数据流

```text
ProviderState + explicit-provider-ready flag
  -> ProviderConfigurationProjection.readiness()       [唯一判定]
      -> RuntimeIdentityPort.provider_readiness()
          -> AgentRuntime.chat 读取一次 snapshot 后决定是否发送
      -> ProviderController.provider_readiness           [只委托，不重算]
          -> MetaAgent
          -> CodingSessionBackendAdapter
          -> LionCodingSession / SettingsPort
              -> /api/status 读取一次 snapshot
                   api_configured = snapshot.ready
                   provider_blocker_code = snapshot.blocker_code
              -> Desktop strict decoder（只校验，首版不改变 UI）
```

`ProviderController._apply_target_state()` 已在 Provider 构建和替换成功后才提交 `_state` 并 `_sync()` projection：`lion_code/runtime/provider.py:435-490`。工厂失败保持旧 Provider、view、context、recorder 不变：`tests/test_provider_controller.py:170-192`。因此 readiness 不需要错误缓存或“最近失败”状态；成功后自然更新，失败时保持旧 snapshot。

Runtime 和 `/api/status` 都应各读取一次完整 `ProviderReadiness`，再派生 bool/code，避免分两次读取时跨过一次配置提交而得到互相矛盾的字段。

### REST / TUI / Desktop 边界

#### REST：需要进入，但只增加一个 nullable code

`/api/status` 已是产品 metadata 的 Provider 状态投影：`lion_code/server/models.py:117-128`、`lion_code/server/app.py:185-200`。首版应新增：

```json
{
  "api_configured": false,
  "provider_blocker_code": "provider_configuration_required"
}
```

ready 时 `provider_blocker_code` 必须是 `null`。不新增嵌套 dimensions、repair target、时间戳或文案。保留 `api_configured` 为 required bool，现有客户端行为不变；新客户端可依赖稳定 code，用户文案仍由客户端决定。

#### Desktop：只跨严格协议解码，不跨 UI 行为

Desktop 的 status 是显式 TypeScript 接口并严格校验：`desktop/src/renderer/src/backend.ts:26-38,258-271`；spec 也要求 malformed status 是显式 metadata error：`.trellis/spec/frontend/desktop-chat-experience.md:63-64`。既然 REST 新字段是正式契约，Desktop 必须把它加入 `ServerStatus` 与 decoder，并校验：

- 仅允许 `null` 或 `"provider_configuration_required"`；
- `api_configured=true` 必须配 `null`；
- `api_configured=false` 必须配该 code；
- 缺字段、未知 code、bool/code 矛盾均拒绝。

首版 `WorkspaceShell` 不读取 code，不改变自动打开设置、placeholder、错误文案或 repair routing。现有行为继续只依赖 `api_configured`：`desktop/src/renderer/src/WorkspaceShell.tsx:44-49,178-189`；对应 spec 在 `.trellis/spec/frontend/desktop-chat-experience.md:75-77,98-99`。

#### TUI：不需要 UI 改动

TUI 已通过 Application session 的 `api_configured` 在首跑打开 `/model` 表单，并在后续选择 picker：`lion_code/tui/app.py:789-805,1312-1327`。首版所有非 ready 都只有同一个修复目的地，因此让 TUI分支读取 blocker code 没有新增行为价值。只要 Application 的兼容 bool 改为单一 readiness 派生，TUI 会自动得到统一结果；不改 notice 文案、不新增状态组件。

#### WebSocket / canonical AssistantMessage：不进入首版

`AgentRuntime.chat` 目前在发送前用 bool 产生可见 terminal assistant error，且不发 Provider 请求：`lion_code/runtime/agent.py:332-354`。它应改为读取完整 readiness snapshot，但首版不把 blocker code塞入 `AssistantMessage`、WireModel 或 WebSocket event。REST status 已提供机器可读 code；扩大 canonical message schema 会带来 JSONL、恢复、Renderer 协议和兼容成本，却没有第二个处理动作。

### 与 Maka 的适用边界

Maka 有两层不同契约，必须区分：

1. `isConnectionReady` 是纯同步 connection 判定，调用方预先解析 credential；唯一 helper 固定失败顺序，并返回 `{ready}` 或 `{ready:false, reason}`：`D:/harness agent/maka/packages/core/src/connection-readiness.ts:20-41,56-78,101-157`。
2. `deriveTaskSubmissionReadiness` 才聚合 runtime、model target、workspace、requested capability，并引入 `ready / repair_required / unavailable / unknown`、authority、checkedAt、repairTarget 和 dimensions：`D:/harness agent/maka/packages/core/src/task-submission-readiness.ts:27-75,84-133`。测试验证 credential unknown、runtime/workspace unavailable 与仅 requested capability 参与：`D:/harness agent/maka/packages/core/src/__tests__/task-submission-readiness.test.ts:28-94`。

Lion 当前 task 是 Provider projection，不是 task submission admission。Lion 没有 credential unresolved authority、Provider catalog、权威 model capability catalog或 workspace/runtime readiness 聚合器。首版只借鉴“单一纯判定 + 稳定机器 code”，不复制第二层 taxonomy。

### 兼容策略

- `api_configured` 在 Python public/API port、REST 与 Desktop status 中继续存在且仍为 required bool；唯一变化是它不再由各层独立计算。
- `ProviderConfigurationProjection.is_api_configured()` 保留为兼容方法，内部只返回 `readiness().ready`。
- `ProviderController.api_configured` 保留为兼容 property，内部只委托 projection readiness。
- REST 新增 required nullable `provider_blocker_code`；Desktop 与 sidecar 同版本交付，decoder 同步收紧。没有必要为旧 sidecar 增加 optional fallback。
- 用户可见“API 未配置”文案、首跑设置弹窗、TUI `/model` 路由和 assistant error 的 canonical 形态不变。
- 配置成功后同步 projection；配置构建/替换失败不提交，因此 bool/code 都保持旧值，不把 transient exception 变成 durable readiness。

### 受影响文件

#### 必须修改的产品代码

- `lion_code/runtime/provider.py` — 定义 frozen `ProviderReadiness` 与唯一 code；projection 唯一判定；Controller 只委托；保留 `api_configured` 兼容派生。
- `lion_code/composition/ports.py` — `RuntimeIdentityPort` 接收 readiness callable，并由 snapshot 派生兼容 bool。
- `lion_code/composition/agent_builder.py` — 把 projection readiness 接到 Runtime identity；不得捕获未来 Controller。
- `lion_code/runtime/agent.py` — 发送前只读取一次 readiness snapshot；保留现有 assistant error 与零 Provider 请求行为。
- `lion_code/meta_agent.py` — 暴露只读 `provider_readiness`，`api_configured` 由其派生；不新增写能力。
- `lion_code/adapters/coding_session_backend.py` — 委托 readiness。
- `lion_code/application/ports.py` — `SettingsPort` 增加只读 readiness；不依赖 Runtime concrete owner。
- `lion_code/application/session.py` — 委托 readiness，并保留兼容 bool。
- `lion_code/server/models.py` — status 增加 nullable literal blocker code。
- `lion_code/server/app.py` — 一次读取 snapshot，同时序列化 bool/code。
- `desktop/src/renderer/src/backend.ts` — 扩展 `ServerStatus` 与严格 decoder；不改 UI。

#### 必须或直接受影响的测试

- `tests/test_provider_controller.py` — 投影 truth table、成功同步、失败保持旧 snapshot、Controller 与 projection 一致。
- `tests/integration/test_meta_agent.py` — concrete Provider 无 key 时 Runtime 与产品 readiness 都为 ready；更新 MetaAgent public surface 精确集合。
- `tests/test_agent_run.py` — 非 ready 时 assistant error 可见且 Provider 未调用；ready 时正常发送。
- `tests/architecture/test_runtime_ownership.py` — 继续证明 Runtime/Capability/SubAgent reachable graph 不可达 Controller，readiness callback 只闭包 projection。
- `tests/server/test_server_api.py` — `/status` ready/null 与 blocked/code 两组，以及 bool/code 不变量。
- `tests/application/fakes.py` 及引用该 fake 的定向测试 — fake 提供一致的 readiness snapshot，避免继续把 bool 作为第二真值源。
- `desktop/tests/renderer/assistantRuntime.test.ts`、`desktop/tests/renderer/WorkspaceShell.test.tsx` — status fixture 加正式字段；新增 unknown/missing/mismatched code 被拒绝的 decoder/metadata 断言。
- `desktop/e2e/chat-protocol.spec.ts` — mock status fixture 同步契约字段；无需新增 UI 场景。

#### 应检查但首版不应修改

- `lion_code/tui/app.py`、`tests/tui/**` — 行为通过兼容 bool 自动统一，无新分支。
- `desktop/src/renderer/src/WorkspaceShell.tsx` — 首版不消费 blocker code。
- `lion_code/core/messages.py`、`lion_code/server/bridge.py`、`desktop/src/shared/chat.ts` — 不改变 canonical message / WebSocket schema。
- `lion_code/application/provider_settings.py` — `known_models` 不是 readiness authority。

### 定向测试矩阵

| 层 | 场景 | 预期 |
| --- | --- | --- |
| Projection | concrete Provider binding，无 key | `ready=True`、code `None`；修复当前 Runtime/产品分裂 |
| Projection | Anthropic 有 key | ready / `None` |
| Projection | OpenAI-compatible 有 key和 base URL | ready / `None` |
| Projection | 无 key | blocked / `provider_configuration_required` |
| Projection | OpenAI-compatible 缺 base URL | blocked / 同一 code |
| Controller transaction | 配置成功 | state 与 projection 同步；Controller/Runtime/Product 读值一致 |
| Controller transaction | Provider factory 或 replace 失败 | 旧 state、旧 readiness、旧 Provider 保持不变 |
| AgentRuntime | blocked chat | 不进入 `ensure_ready`/Provider request；现有 terminal assistant error 与 notice 保持 |
| AgentRuntime | concrete Provider 无 key | 正常发送，不被产品 status 误报为未配置 |
| REST | ready status | `api_configured=true` 且 code `null` |
| REST | blocked status | `api_configured=false` 且稳定 code |
| Desktop decoder | 两个合法组合 | 接受并保留 metadata |
| Desktop decoder | 缺字段、未知 code、bool/code 冲突 | 明确 metadata error |
| TUI | blocked mount / `/model` | 继续走已有表单；无需 code 分支 |
| Architecture | Minimal/Coding/Full reachable graph | AgentRuntime、Session、Capability、SubAgent 不可达 Controller |

建议最小验证命令（不要跑全量 suite）：

```powershell
pytest tests/test_provider_controller.py tests/test_agent_run.py tests/integration/test_meta_agent.py tests/server/test_server_api.py tests/architecture/test_runtime_ownership.py
Set-Location desktop
npm test -- --run tests/renderer/assistantRuntime.test.ts tests/renderer/WorkspaceShell.test.tsx
npm run typecheck
```

若 `chat-protocol.spec.ts` 仅改 fixture，Vitest/TypeScript 已能覆盖协议编译；除非实现实际改变 Desktop UI 行为，不需要跑 Electron Playwright 或 real-sidecar e2e。

### 风险

- **最大风险：只在 Controller 改公式。** 这会让产品面与 Runtime 暂时一致，但仍保留两个判定源；未来 projection 规则变化会再次分裂。
- **snapshot 撕裂：** `/status` 若分别调用 bool 与 code getter，配置提交并发时可能组合出矛盾字段；必须一次读取 immutable readiness。
- **错误 taxonomy 过早承诺：** 把 transient Provider 构造异常、网络探测或 workspace 状态写成 Provider blocker，会把非权威事实持久化到产品契约。
- **Desktop 宽松解码：** REST 增加字段而 TypeScript decoder 不校验，会违反当前 strict metadata spec，并让未知 code 静默进入 Renderer。
- **假兼容：** 不要把新字段设 optional 再默认从 `api_configured` 猜 code；Desktop 与 sidecar 是同版本交付，fallback 会重新形成第二判定。
- **公共 surface 精确测试：** `MetaAgent` public set 有精确断言，新增 `provider_readiness` 必须有意更新；它仍是通用 Provider 只读能力，不是产品 feature 泄漏。

### 明确不做项

- 不引入 `ready / repair_required / unavailable / unknown` 四态。
- 不引入 dimensions、authority、checkedAt、repairTarget、blockers 数组或聚合优先级。
- 不判断 workspace、Runtime host、Session admission、Capability 或资源可用性。
- 不建立 Provider catalog，不用 `known_models` 拒绝自由字符串模型，不判断模型 chat capability。
- 不把历史成功、`last_test_status`、健康探测、网络连通性或原始异常当当前 readiness。
- 不缓存 Provider 构造失败；事务失败继续直接返回配置错误并保持旧 readiness。
- 不为 key/base URL 各建 blocker code；出现不同修复动作前只有一个稳定 code。
- 不修改 TUI/Desktop 用户文案、弹窗策略或 repair routing。
- 不给 WebSocket event、AssistantMessage、JSONL history 增加 blocker 字段。
- 不新增 Manager、Registry、Resolver、Catalog、第二 projection 或第二可写状态。

## Files Found

- `lion_code/runtime/provider.py` — 当前 projection 与 Controller 分别计算 API configured，且 `_provider_ready` 只在 projection 生效。
- `lion_code/composition/agent_builder.py` — projection 在 Controller 前创建并接入 Runtime identity。
- `lion_code/composition/ports.py` — Runtime 的 controller-free identity 窄口。
- `lion_code/runtime/agent.py` — 发送前 gate 与 canonical error 落点。
- `lion_code/meta_agent.py` — 产品 facade 当前通过 Controller 读取另一套 bool。
- `lion_code/application/ports.py`、`lion_code/application/session.py`、`lion_code/adapters/coding_session_backend.py` — 产品状态到 TUI/Server 的窄腰链路。
- `lion_code/server/models.py`、`lion_code/server/app.py` — `/api/status` schema 与序列化。
- `lion_code/tui/app.py` — 现有 bool 已足够路由到 `/model`。
- `desktop/src/renderer/src/backend.ts`、`desktop/src/renderer/src/WorkspaceShell.tsx` — strict status decoder 与 bool 驱动的首跑 UI。
- `tests/test_provider_controller.py` — Provider 原子替换、projection 同步和失败保持测试。
- `tests/architecture/test_runtime_ownership.py` — Controller reachable-object-graph 禁令。
- `tests/architecture/test_composition_profiles.py` — concrete Provider 无 key 仍可运行的现成证据。
- `D:/harness agent/maka/packages/core/src/connection-readiness.ts` — Maka 单 connection 纯 readiness 判定。
- `D:/harness agent/maka/packages/core/src/task-submission-readiness.ts` — Maka 更大范围四态聚合，首版不应复制。

## Code Patterns

- 单向 ownership：projection 在 Controller 前创建，Controller 只在成功提交后 `_sync`；见 `.trellis/spec/backend/four-layer-ownership.md:23-37`、`.trellis/spec/backend/runtime-boundaries.md:53-70,132-142`。
- Provider 配置的唯一写 owner 是 Controller，Projection/MetaAgent/SettingsPort 只读；见 `docs/architecture/state-ownership.md:8-18,29-30`。
- Desktop status 采用显式 interface + predicate decoder，而不是 permissive cast；见 `desktop/src/renderer/src/backend.ts:26-38,104-106,258-271`。
- 事务式 Provider replacement：先构建、成功后提交 projection，失败保留旧状态；见 `lion_code/runtime/provider.py:435-490`、`tests/test_provider_controller.py:123-192`。

## External References

- 无互联网或第三方文档依赖。
- Maka 对照基于本次通过 `D:/harness agent/maka/.codegraph` 重新读取的当前源码；任务决策包记录的取证版本为 `3eee0bd18af4263ec30e9ccc75b8a6f7b8a9680e`，但本研究没有运行 Git 命令确认当前 HEAD。
- Lion 对照基于本次通过 `D:/harness agent/Lion/.codegraph` 重新读取的当前源码；任务决策包记录的取证版本为 `41ba83372ecce78c696cbc803626b0ed54df5fd9`，但本研究没有运行 Git 命令确认当前 HEAD。

## Related Specs

- `.trellis/spec/backend/four-layer-ownership.md:23-37` — Runtime/Controller 双向禁令与 projection controller-free 回调。
- `.trellis/spec/backend/runtime-boundaries.md:53-70,132-142` — topological composition、projection 只读职责和成功后同步。
- `.trellis/spec/frontend/desktop-chat-experience.md:63-77,89-99` — strict REST metadata、`api_configured` 首跑与发送失败行为。
- `docs/architecture/boundaries.md:31-43` — Runtime 不能持有 Controller，Composition 创建只读 projection。
- `docs/architecture/state-ownership.md:8-18,29-30` — Provider state 单一所有者与只读者列表。

## Caveats / Not Found

- 没有发现 Lion 中 credential unresolved/unknown 的现行 authority；API key 是同步字符串事实，因此首版不能诚实地产生 `unknown`。
- 没有发现可在服务存活时代表 Provider `unavailable` 的稳定事实；初始 factory 失败会阻止构造，配置 factory/replace 失败由事务直接报错且不提交。
- 没有发现权威 Provider/model catalog；`known_models` 是设置辅助列表，不足以产生 model blocker。
- 当前没有针对“concrete Provider 无 key 时 `MetaAgent.api_configured` 应为 true”的直接回归测试；这是首要新增用例。
- 未运行任何测试、Git 命令或产品代码；本文件是规划研究，不是实现验证。
