# 权限与安全平面技术设计

## 1. 架构与边界

全部安全平面代码落 Kernel 工具子系统 `lion_code/tooling/`（分层归属见
`four-layer-ownership.md:10`，即 PRD D4 修正）。禁止进入：`runtime/`
（会话与对话状态）、`meta_agent.py`、Capability SPI、`session_runtime/`。
安全信号向 Agent 层的流动只走既有公开路径：ToolResult 内容 / details
（与 PR-S1 rollback notice 同款 Core adapter 路径）。

新增文件：

- `lion_code/tooling/secret_provider.py` —— SecretStore（三源加载，v1 以 .env
  为主）+ SecretRef 元数据 + HMAC 指纹族预计算。
- `lion_code/tooling/output_sanitizer.py` —— `OutputSanitizerMiddleware`
  （post phase）。
- `lion_code/tooling/egress_guard.py` —— `EgressGuardMiddleware`（pre phase）
  + `EgressWhitelist`（(host, direction) 表）。

扩展文件：

- `lion_code/tooling/permission.py` —— S5 谓词表判定 + 授权快照 + shadow 对照。
- `lion_code/tooling/audit.py` —— ExecutionEvent 补字段（见 §4）。
- `lion_code/tooling/execution.py` —— 子进程 secret env 注入。
- `lion_code/composition/agent_builder.py:700` —— 链组装；
  `ToolBindings` 增加 secret_provider / output_sanitizer / egress_guard
  及对应 enable 开关（模式对齐既有 workspace_snapshot / audit_log）。

middleware 链（现状态 + 插入点）：

```
pre （声明序）：Cancellation → WorkspaceSnapshot → PreToolHook
              → Permission → EgressGuard(S3)
post（声明序）：OutputSanitizer(S2) → ReadFreshness → ResultPolicy → Audit
```

理由：redact 必须发生在结果进入 ResultStore 与审计之前，故 sanitizer 是
post 链首位；出口判定在权限之后、执行之前。web_fetch 的出口检查在
middleware 层完成，不改 `tools.py:_web_fetch` 本体，避免出现第二条路径。

## 2. 数据流与契约

### 2.1 Secret Boundary（PR-S2）

- `SecretRef = {name, configured}`；模型可见面只有 reference 元数据，
  值永不进入 ToolResult、审计、日志。
- 注入：run_shell 参数新增可选 `secrets: [ref 名]`；
  `LocalCommandExecutionBackend.run` 启动子进程前从 SecretStore 取值
  注入环境块，值直达命令进程。
- 指纹族：每个 secret 预计算 `HMAC(secret)`、`HMAC(base64(secret))`、
  `HMAC(hex(secret))`、`HMAC(urlencode(secret))`；HMAC 密钥文件
  `~/.lion/sanitizer.key`（workspace 外，0600）。
- Sanitizer：按分隔符切分（空白 / 行 / 引号界）后逐段与指纹族比对，
  命中原地替换 `***`，命中计数写入 `ToolResult.details.sanitizer_hits`；
  禁止全输出滑窗哈希；sanitizer 只持有指纹不持有明文。
- 闭环边界如实标注（G7）：只对已登记 secret 闭环，发现完整性是显式
  残余风险，记入 security-design.md 残余风险登记表。

### 2.2 Egress Guard（PR-S3）

- Level A（guaranteed）：`EgressGuardMiddleware` pre 相拦截 `web_fetch`：
  解析 `url` 参数取 host → 查 `(host, direction=fetch)` 白名单；
  未命中 → block（`ToolResult(is_error=True,
  "destination not whitelisted: <host>")`）+ 审计行；命中 → 放行，
  并对 URL 全串（含 query）做指纹扫描——GET query 同样是 exfil 通道，
  命中即按 deny(secret.fingerprint_hit and egress.outbound) 阻断。
- 白名单 v1 初始集 = provider 配置 base_url 的 host（composition root
  派生注入）；其余默认 block（PRD D1：最小信任 + 审计驱动加白）。
  用户在 settings 加白；配置发现沿用 `load_permission_rules` 的
  home / cwd 模式。
- Level B（best effort）：run_shell pre 相用正则提取 URL/域名，写审计行
  `best_effort=true`，不阻断、不做意图分析；高频 destination 作为用户
  加白候选。
- 方向维度（G4）：白名单条目为 `(host, direction)`；web_fetch 只产生
  fetch 事实；push/upload 类谓词在 S5 进入 require_confirmation。

### 2.3 Authorization Policy（PR-S5）

- 谓词表配置（settings 文件，格式对齐现有 allow/deny 规则）：
  workspace.mutation、egress.(destination, direction)、shell.command
  前缀、工具参数等值。判定 = 机械查表；语义动作名只作审计标签。
- 事实源分级（G3）：参数级事实标 guaranteed；命令字符串事实标
  best_effort；分级随判定结果入审计。
- 接线：`PermissionPolicy.check` 扩展为「谓词表 → 现有能力判定
  （read_only / acceptEdits / is_dangerous）→ confirm」；
  require_confirmation 复用 `PermissionMiddleware` 现有 confirm_fn +
  `is_confirmed` 确认缓存（`middleware.py:145`）。
- 预算外 fallback：default 模式 → confirm_fn（现状不变）；
  dontAsk → 优雅停机替换现有 auto-deny（`permission.py` 的
  `Auto-denied (dontAsk mode)` 分支）：返回结构化 ToolResult
  （budget_exceeded + 触发谓词 + handoff 指令），模型可见通知走
  ToolResult 内容回流；会话挂起信号经公开结果 / 事件流由 Supervisor
  平面消费，安全代码不反向依赖 runtime/。
- 授权快照：任务启动时把授权声明写入审计
  （authorization_source = task-grant#id）。
- shadow 迁移：旧 allow/deny 规则并行判定、只记录
  （notes: shadow_old=allow/deny），观察期后删除旧规则判定路径。

### 2.4 信任域声明（G2）

`docs/security-design.md` 显式声明信任域 = {本机 + LLM Provider}：
providers 流量不设卡；T2 防护对象是经 Agent 出口去向第三方目的地；
bypassPermissions 的 allow-all 语义保持，其风险定位记入残余风险登记表。

## 3. 审计扩展（R4）

ExecutionEvent（`audit.py:20`）已有 destination、fingerprint_hit、
authorization_source；本任务补：

- `direction: str | None`
- `sanitizer_hits: int = 0`
- `best_effort: bool | None`

append-only、存 workspace 外（PR-S1 既有行为保持），只记录不干预。

## 4. 兼容与迁移

- 不留兼容层（项目原则 1）：shadow 是迁移观察手段，观察期后旧 allow/deny
  判定路径整体删除，不是长期并存。
- dontAsk 的 confirm 语义从 auto-deny 变为优雅停机，是行为变更：
  同步更新 `.trellis/spec/backend/` 相关 spec 与 `docs/tui.md`。
- 快照机制不动（PRD D3）。

## 5. 关键权衡

- sanitizer 挂 post 链首位而非仅 executor 输出：全工具输出过一次
  线性指纹比对，成本可忽略；换取 G1 闭环成立（read_file/grep_search/
  web_fetch 全覆盖）。
- Level B 不阻断：诚实标注 best_effort 优于虚假承诺；完整阻断 defer
  给 S4 Sandbox（由残余风险登记表立项）。
- 白名单最小信任（D1）：初期 web_fetch 摩擦大，换最小信任面；
  用 Level B 审计数据驱动加白，演进有据。
- T3 v1 用命令串谓词（D2）：当前无 git/publish 专用工具，参数级事实源
  不存在；不预建抽象（项目原则 2），审计数据决定是否立项专用工具。

## 6. 运维与回滚

- 每个 PR 通过 ToolBindings 开关独立启停
  （enable_secret_boundary / enable_egress_guard / enable_predicate_policy），
  关闭即回到现状行为，无需回滚代码。
- PR 级回滚点：各 PR squash merge 前的 commit。
- 快照与审计平面（PR-S1）不受本任务影响。
