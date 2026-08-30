# 统一 Provider readiness 投影与稳定 blocker code

## Goal

消除 Lion 中 Runtime 与产品读取面各自计算 Provider readiness 的语义分裂，让一次不可变的 Provider readiness 投影成为唯一判定来源；在不改变现有发送错误、首跑设置和 `api_configured` 调用方行为的前提下，为 `/api/status` 增加一个稳定、可机器消费的 blocker code。

## User value

同一 Provider 配置在 Runtime、Application、REST、TUI 和 Desktop 不再出现“实际可以运行但界面显示未配置”的矛盾。后续设置入口可以依据稳定 code 诊断配置问题，而不需要解析错误文案或复制 Provider 规则。

## Confirmed facts

- `ProviderConfigurationProjection.is_api_configured()` 已把显式注入的 concrete Provider 视为 ready，并供 Runtime 读取。
- `ProviderController.api_configured` 在 `lion_code/runtime/provider.py:249-257` 重新计算 key/base URL，遗漏显式注入 Provider 的 ready 事实。
- `MetaAgent`、Application/REST、TUI 和 Desktop status 读取 Controller 或其派生的 bool，因此存在第二个 readiness 公式。
- Composition 已在 `ProviderController` 之前创建 controller-free projection；Controller 在成功状态提交后同步 projection，配置构建或替换失败时保留旧状态。
- Maka 的可借鉴部分是“单一纯判定 + 稳定机器 code”，不是把 task-submission 的 workspace、capability、历史探测和四态 taxonomy 搬入 Lion。

## Requirements

### R1. Single readiness source

在现有 `ProviderConfigurationProjection` 内定义不可变 `ProviderReadiness` 及唯一 blocker code。`readiness()` 必须一次返回完整 snapshot：ready 时 code 为 `None`，非 ready 时 code 为 `provider_configuration_required`。显式注入 concrete Provider 保持 ready；其余配置继续沿用当前 key/base URL 规则。

### R2. Derive every bool from the snapshot

`is_api_configured()`、`ProviderController.api_configured`、`MetaAgent.api_configured`、Application `api_configured` 和 REST `api_configured` 不得保留独立公式，只能由同一 `ProviderReadiness.ready` 派生。Runtime 发送门一次读取 snapshot，不能分别读取 bool 和 code。

### R3. Stable REST projection

`ServerStatusResponse` 和 `/api/status` 增加 required nullable 字段 `provider_blocker_code`：ready 时为 `null`，blocked 时为 `provider_configuration_required`。保留现有 required bool `api_configured`。状态序列化必须从一次 readiness snapshot 派生两个字段，不暴露凭证、原始异常、网络探测或内部状态。

### R4. Strict Desktop decoding, unchanged UI behavior

Desktop `ServerStatus` 和 status decoder 必须认识并严格校验该字段：只接受 `null` 或 `provider_configuration_required`，并拒绝缺字段、未知 code 以及 bool/code 矛盾。首版不修改 `WorkspaceShell` 的设置弹窗、文案或 repair routing；TUI 不新增 blocker 分支。

### R5. Preserve transaction and error contracts

Provider 成功配置后 readiness 与 authoritative state 同步；Provider factory、replace 或写盘失败时旧 Provider、旧 state、旧 readiness 保持不变。非 ready chat 继续不发 Provider 请求并产生现有 canonical assistant error；不把 blocker code 放进 AssistantMessage、WebSocket event、JSONL 或新的持久化状态。

### R6. Verify the observable boundary

新增或更新定向测试，覆盖 concrete Provider 无 key、Anthropic/OpenAI-compatible 配置、缺配置、状态切换失败、Runtime/Controller/Application/REST 一致性、严格 Desktop 解码和既有 TUI/首跑行为。只运行与本次变更直接相关的测试及必要的类型/格式检查。

## Acceptance Criteria

- [ ] AC1：对 concrete Provider binding，即使没有 API key，Projection、Controller、MetaAgent、Application 和 REST 都报告 `api_configured=true`、`provider_blocker_code=null`；Runtime 正常进入 Provider 调用。
- [ ] AC2：无 key 或 OpenAI-compatible 缺 base URL 时，所有读取面报告 `api_configured=false`、`provider_blocker_code="provider_configuration_required"`；ready/code 不变量始终成立。
- [ ] AC3：任一 Provider readiness bool 都能追溯到同一个 `ProviderReadiness` snapshot；代码中不存在第二套 key/base URL readiness 公式，`/api/status` 不会组合出撕裂字段。
- [ ] AC4：Provider 配置成功同步 state 与 projection；构建、替换或持久化失败后旧 state、旧 Provider、旧 readiness 均保持，现有错误语义不变。
- [ ] AC5：非 ready chat 不产生 Provider request，现有 canonical assistant error 和 settled/idle 行为不变；ready 的显式注入 Provider 不被错误阻断。
- [ ] AC6：Desktop strict decoder 接受两个合法组合，拒绝缺字段、未知 code 和 bool/code 矛盾；首版 UI 不因新字段改变既有设置打开规则。TUI 仍通过兼容 bool 走已有 `/model` 路径。
- [ ] AC7：受影响的 Python/TypeScript 定向测试和 `git diff --check` 通过；不修改代码范围之外的文件，不新增 Manager、Registry、Catalog、第二 projection 或持久化 schema。

## Out of scope

- 不引入 `ready/repair_required/unavailable/unknown` 四态、dimensions、authority、checkedAt、repairTarget 或聚合 blocker 列表。
- 不判断 workspace、Runtime host、Session admission、Capability、网络连通性、历史成功或 Provider 健康探测。
- 不把 `known_models` 当作权威 model catalog；首版不把空 model 或 chat capability 混入 readiness。
- 不为 key、base URL 分别冻结新的 code；当前相同修复目的只使用一个稳定 code。
- 不修改 TUI/桌面用户文案、设置路由、AssistantMessage、WebSocket、JSONL、Provider factory 或 Session history。
- 不保留新的兼容 fallback 或从 `api_configured` 猜测缺失 code；Desktop 与 sidecar 同版本交付，协议字段保持严格。

## Open questions

无阻塞性问题。首版是否进入 REST 和 Desktop decoder、是否保持 TUI/UI 行为不变，已依据当前对象图和现有严格协议契约确定。
