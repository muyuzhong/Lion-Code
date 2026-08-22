# 权限与安全平面技术设计（YAGNI 削减后）

## 1. 架构与边界

全部安全平面代码落 Kernel 工具子系统 `lion_code/tooling/`（分层归属见
`four-layer-ownership.md:10`，PRD D4 修正）。禁止进入：`runtime/`
（会话与对话状态）、`meta_agent.py`、Capability SPI、`session_runtime/`。
安全信号向 Agent 层的流动只走既有公开路径：ToolResult 内容 / details
（与 PR-S1 rollback notice 同款 Core adapter 路径）。

新增文件：

- `lion_code/tooling/secret_provider.py` —— SecretStore（.env 全量 +
  进程 env 名字模式过滤）+ HMAC 指纹族预计算 + 密钥文件自动生成。
- `lion_code/tooling/output_sanitizer.py` —— `OutputSanitizerMiddleware`
  （post phase）。
- `lion_code/tooling/egress_guard.py` —— `EgressGuardMiddleware`（pre phase）
  + `EgressWhitelist`（host 集合）。

扩展文件：

- `lion_code/tooling/permission.py` —— dontAsk 优雅停机分支 + 授权快照 +
  push 类目的地 confirm 接线（复用现有结构，无新判定系统）。
- `lion_code/tooling/audit.py` —— ExecutionEvent 补 `sanitizer_hits`、
  `best_effort` 两字段。
- `lion_code/composition/agent_builder.py:700` —— 链组装；
  `ToolBindings` 增加 secret_store / output_sanitizer / egress_guard
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

### 2.1 Secret Boundary —— redact-only（PR-S2）

- SecretStore 来源：workspace `.env` 全量键值；进程环境变量中名字匹配
  `*_KEY` / `*_TOKEN` / `*_SECRET` / `*_PASSWORD` 的条目（不注册则
  `printenv` 是 v1 的 T1 现成洞）。keychain 源 defer。
- 指纹族：`HMAC(secret)` 与 `HMAC(base64(secret))` 两个变体；
  hex/urlencode 等审计出现漏网案例再加（常数行）。
  密钥 `~/.lion_code/sanitizer.key` 自动生成（0600），无轮换无配置面；
  store 只输出指纹，明文不出 SecretStore。
- Sanitizer：按分隔符切分（空白 / 行 / 引号界）后逐段与指纹族比对，
  命中原地替换 `***`，命中计数写入 `ToolResult.details.sanitizer_hits`；
  禁止全输出滑窗哈希。
- 闭环边界如实标注（G7）：只对已登记 secret 闭环，发现完整性是显式
  残余风险，记入 security-design.md 残余风险登记表。
- 注入延后（D6）：子进程本就继承父 env（`execution.py:29`），
  .env 凭据的显式注入随专用工具立项；v1 不改 execution.py、
  不改 run_shell schema。

### 2.2 Egress Guard（PR-S3）

- Level A（guaranteed）：`EgressGuardMiddleware` pre 相拦截 `web_fetch`：
  解析 `url` 参数取 host → 查 host 白名单；未命中 → block
  （`ToolResult(is_error=True, "destination not whitelisted: <host>")`）
  + 审计行；命中 → 放行，并对 URL 全串（含 query）做指纹扫描——
  GET query 是 exfil 通道，命中即阻断（deny(secret_hit and
  egress.outbound) 的落地形态）。
- 白名单 v1 = provider 配置 base_url 的 host（composition root 派生注入）
  + 用户 settings 加白条目（配置发现沿用 `load_permission_rules` 的
  home / cwd 模式）；其余默认 block（D1）。
- Level B（best effort）：run_shell pre 相正则提取 URL，写审计行
  `best_effort=true`，不阻断、不做意图分析；高频 destination 是 D1 的
  加白候选数据源。
- 方向维度延后（D7）：v1 白名单是 host 集合；push/upload 语境由 R3 的
  confirm 接线处理，S4 / 专用工具落地时再引入 direction 列。

### 2.3 授权收尾（PR-S5-lite，无新判定系统）

- dontAsk 优雅停机（D8）：`permission.py` 的
  `Auto-denied (dontAsk mode)` 分支改为返回结构化 ToolResult——
  `budget_exceeded` 标记 + 触发原因 + handoff 指令文本（告知模型任务已
  挂起、人类决策请求已生成），模型可见通知走 ToolResult 内容回流；
  不做 git commit，进度保存/恢复归 Supervisor 平面（08-17-pr10 职责）；
  停机事件入审计。
- 授权快照：任务/会话启动时向审计写一条授权声明记录
  （authorization_source = session-grant，含 mode 与已加载规则摘要）。
- push 类目的地 confirm 接线：shell 命令字符串中出现已知 push/upload
  语境（如 `git push`、`npm publish`，与既有 `is_dangerous` 同层的机械
  匹配）→ 进入现有 confirm_fn + `is_confirmed` 确认缓存路径；
  不建谓词引擎（D5）——工具/前缀粒度的 allow/deny 继续用现有 settings
  规则表达。

### 2.4 信任域声明（G2）

`docs/security-design.md` 显式声明信任域 = {本机 + LLM Provider}：
providers 流量不设卡；T2 防护对象是经 Agent 出口去向第三方目的地；
bypassPermissions 的 allow-all 语义保持，其风险定位记入残余风险登记表。

## 3. 审计扩展（R4）

ExecutionEvent（`audit.py:20`）已有 destination、fingerprint_hit、
authorization_source；本任务补：

- `sanitizer_hits: int = 0`
- `best_effort: bool | None`

append-only、存 workspace 外（PR-S1 既有行为保持），只记录不干预。

## 4. 兼容与迁移

- 不留兼容层（项目原则 1）。无 shadow 迁移（D5：没有新判定路径）。
- dontAsk 的 confirm 语义从 auto-deny 变为优雅停机，是行为变更：
  同步更新 `.trellis/spec/backend/` 相关 spec 与 `docs/tui.md`。
- 快照机制不动（PRD D3）。

## 5. 关键权衡

- sanitizer 挂 post 链首位覆盖全部工具：一个 middleware 挂一个窄腰，
  比维护"哪些工具要过滤"的清单更简单；成本是每条输出一次线性指纹比对。
- redact-only（D6）：T1 防护完整；代价是 v1 期间 Agent 无法使用 .env
  凭据执行操作——与现状一致，零回退。
- Level B 不阻断：诚实标注 best_effort 优于虚假承诺；完整阻断 defer
  给 S4 Sandbox。
- 白名单最小信任（D1）：初期 web_fetch 摩擦大，换最小信任面；
  Level B 审计数据驱动加白，演进有据。
- 不建谓词引擎（D5）：现有规则格式已覆盖全部机械事实表达；
  真不够表达时再立项，不预防性抽象（项目原则 2）。

## 6. 运维与回滚

- 每个 PR 通过 ToolBindings 开关独立启停
  （enable_secret_boundary / enable_egress_guard），关闭即回到现状行为。
- PR 级回滚点：各 PR squash merge 前的 commit。
- 快照与审计平面（PR-S1）不受本任务影响。
