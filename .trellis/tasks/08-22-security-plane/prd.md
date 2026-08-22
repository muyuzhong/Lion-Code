# 权限与安全平面落地（PR-S2 / S3 / S5）

## Goal

在已落地的 PR-S1（快照 / 审计 / 回滚）之上，交付安全设计的防护部分：
Secret Boundary redaction（PR-S2）、Egress Guard（PR-S3）、授权收尾三件事
（PR-S5-lite：dontAsk 优雅停机、授权快照、egress 接 confirm），封死三类
不可逆伤害（T1 secret 泄漏、T2 内部数据外传、T3 外部系统状态改变）中
当前可防护的路径。设计文本按第一性原理审核的 G1-G7 修正 + YAGNI 削减
（D5-D8）定稿，落地为 `docs/security-design.md`。

核心纪律：机械谓词、零意图理解；承诺强度匹配事实质量；A/B 双层诚实承诺；
信任域显式声明为 {本机 + LLM Provider}；防护优先于能力，投机性复杂度零容忍。

## Background

- 设计方案与审核（G1-G7 缺口）已在前一会话完成；本次规划又按 YAGNI 原则
  做了四项削减（D5-D8），每刀均不削弱威胁模型承诺。
- 实施顺序：Secret Boundary 先行（S3 的 payload 扫描复用其指纹族），
  Egress Guard 先于授权收尾上线（缺位期 fallback = block + audit）。

## Confirmed Facts

1. PR-S1 已落地：`lion_code/tooling/snapshot.py`（manifest + workspace 外拷贝存储、
   git 只读探针、`.git` 路径校验拒绝、tracked 缺失标记、pre-restore 自举快照、
   newest-N + 时间窗 GC）、`lion_code/tooling/audit.py`、
   `lion_code/tooling/runtime.py`（`ToolRuntime.rollback`）、
   `lion_code/tooling/middleware.py`（`WorkspaceSnapshotMiddleware` pre 相无条件快照）。
   契约见 `.trellis/spec/backend/tool-runtime-recovery.md`。
2. 工具面封闭且小：7 个内置工具
   （read_file / write_file / edit_file / list_files / grep_search / run_shell / web_fetch，
   `lion_code/tooling/builtin.py:12`），全部经 `ToolRuntime.execute` +
   `ToolMiddleware` pre/post 链（`lion_code/tooling/middleware.py:22`）。
   post 相 middleware 是 sanitizer 统一入口的现成挂载缝（G1 修正的落点）。
3. 进程内出口现状：`web_fetch`（`lion_code/tools.py:219`，urllib，仅允许 http/https）
   是唯一应用层出口；providers 为 LLM 调用，按信任域声明不设卡；
   MCP 已移除（archive 任务 08-16-pr7b-mcp-total-removal），无浏览器工具。
   Level A 收窄为 web_fetch。
4. 子进程已继承完整父 env：`LocalCommandExecutionBackend.run`
   （`lion_code/tooling/execution.py:29`）未传 env 参数，进程 env 内凭据
   （如 provider API key）本来就直达子进程——注入机制对这类 secret 无增益。
5. 权限面已有骨架且表达力足够：`lion_code/tooling/permission.py`
   （PermissionPolicy：settings 规则 allow/deny + `_matches_rule`
   （`permission.py:128`）已支持 `run_shell(命令前缀*)` 与 `file_path` 等值匹配；
   capabilities 判定 read_only / mutates_workspace / acceptEdits /
   `is_dangerous` + confirm 路径）、`PermissionMiddleware`
   （`lion_code/tooling/middleware.py:145`）、`lion_code/permission_state.py`
   （PermissionMode：default / acceptEdits / bypassPermissions / dontAsk +
   确认缓存 `is_confirmed`）。
6. 有人/无人值守信号：TUI 交互模式与 `--web` 服务模式（`lion_code/__main__.py:44`）
   可区分；dontAsk 语义承载"预算外 → 优雅停机"分支。
7. 分层归属：`tooling/` 属 Kernel（`.trellis/spec/backend/four-layer-ownership.md:10`）。
   安全平面代码落 `lion_code/tooling/`；禁止进入的是 Agent Runtime 层
   （runtime/ 会话与对话状态）、MetaAgent、Capability SPI。
   设计稿 §六 的"禁止进入 Kernel"表述按此修正。
8. T3 无参数级事实源：无 git/publish/deploy 专用工具，git 操作走 run_shell ——
   T3 防护基于命令字符串与现有规则匹配，如实标注 best_effort（G3），
   专用工具 deferred（见 Out of Scope）。

## Requirements

### R1. Secret Boundary —— redact-only（PR-S2）

- SecretStore：v1 两个来源——workspace `.env`（全量键值）+ 进程环境变量
  （仅 `*_KEY` / `*_TOKEN` / `*_SECRET` / `*_PASSWORD` 名字模式；
  不注册进程 env 的 T1 现成洞：`printenv ANTHROPIC_API_KEY`）。
  keychain 源 defer。
- 指纹族：每 secret 预计算 HMAC 原值 + HMAC(base64) 两个变体；
  hex/urlencode 变体等审计出现漏网案例再加（常数行成本）。
  HMAC 密钥文件 `~/.lion_code/sanitizer.key` 自动生成（0600），无轮换无配置面；
  sanitizer 只持有指纹不持有明文。
- OutputSanitizer 为 post-phase middleware（G1 落点）：覆盖全部 7 个工具输出；
  分隔符切分（空白 / 行 / 引号界）后与指纹族线性比对，命中原地替换 `***`；
  禁止全输出滑窗哈希。
- `sanitizer_hits` 计数入审计。
- 闭环边界如实标注（G7）：只对已登记 secret 闭环，发现完整性是显式残余风险。

### R2. Egress Guard（PR-S3）

- Level A（guaranteed）：`EgressGuardMiddleware` pre 相拦截 `web_fetch`：
  解析 `url` 参数取 host → 查白名单（host 集合）；未命中 → block + audit
  （S4 缺位期 fallback，不发明临时确认机制）；命中 → 放行，并对 URL 全串
  （含 query）做指纹扫描——GET query 同样是 exfil 通道，命中即阻断
  （deny(secret_hit and egress.outbound) 的落地形态）。
- 白名单 v1 初始集 = provider 配置 base_url 的 host（composition root 派生注入）；
  其余默认 block（D1：最小信任 + 审计驱动加白），用户在 settings 加白，
  配置发现沿用 `load_permission_rules` 的 home / cwd 模式。
- Level B（best effort）：run_shell pre 相正则提取 URL，写审计行
  `best_effort=true`，不阻断、不做意图分析；高频 destination 是用户加白候选
  （D1 的数据源）。

### R3. 授权收尾三件事（PR-S5-lite）

- dontAsk 预算外从 auto-deny 改为优雅停机：返回结构化 ToolResult
  （budget_exceeded + 触发原因 + handoff 指令文本）+ 审计行；
  不做 git commit（进度保存/恢复归 Supervisor 平面，08-17-pr10 职责）。
- 任务启动时授权快照入审计：mode + 已加载规则摘要（责任归属依据）。
- egress 的 push 类目的地（shell 命令中出现 github.com / pypi.org 等
  push/upload 语境）接入现有 confirm 路径与确认缓存——复用
  `PermissionMiddleware` 的 confirm_fn，不建新判定系统。

### R4. 审计扩展

- ExecutionEvent（`lion_code/tooling/audit.py:20`）已有 destination、
  fingerprint_hit、authorization_source 字段；本任务补充 `sanitizer_hits`
  与 `best_effort`；append-only、存 workspace 外，只记录不干预。

### R5. 设计定稿与门禁文档

- `docs/security-design.md` 按 G1-G7 修正定稿：信任域声明、快照机制对齐
  已落地实现、目录/分层修正、egress 承诺分层、闭环措辞弱化
  （"对已登记 secret 闭环，发现完整性是显式残余风险"）、对手模型
  （prompt injection）与残余风险登记表（S4 Sandbox 立项依据）。
- `docs/advanced-capability-guide.md` 门禁段落：ToolRuntime 是工具调用唯一路径，
  新工具不得绕过 sanitizer / egress / 权限判定。

## Acceptance Criteria

- [x] 注册 secret 在 run_shell / read_file / grep_search / web_fetch 任一输出中
      均被 redact（每条路径各一条测试）；secret 明文不出现在 provider 请求负载
      （tests/integration/test_provider_core_tool_runtime.py 请求负载断言）。
- [x] 进程 env 中名字匹配模式的凭据（如 API key）被注册并在裸值输出形态下 redact
      （注册与输出形态各有测试；真实 printenv 子进程路径跨平台脆弱，不测）。
- [x] web_fetch 请求白名单外 destination 被阻断并产生审计行；白名单内放行；
      provider 流量不受 Egress Guard 影响。
- [x] web_fetch URL query 携带已登记 secret 指纹命中时被阻断并产生审计行。
- [x] run_shell 命令字符串含 URL 时，审计行含 best_effort 标注与提取的 destination。
- [x] dontAsk 模式下预算外动作产生结构化停机 ToolResult（budget_exceeded +
      handoff 文本）与审计行，不触发 git commit。
- [x] 任务启动时的授权快照（mode + 规则摘要）出现在审计中。
- [x] push 类目的地经 run_shell 触发现确认路径（复用现有 confirm 缓存）。
- [x] 架构测试期望值同步更新且全绿；本地质量门禁
      （ruff / mypy / 基线比对）通过；CI 绿。

## Key Decisions

- D1（用户已决）：Level A 白名单最小信任 deny-by-default，初始仅含配置派生的
  provider endpoints，靠 Level B 审计数据驱动加白演进。
- D2（G3）：T3 防护基于命令字符串与现有规则匹配，如实标注 best_effort；
  git/publish 专用工具（参数级事实源）待审计数据证明需要后另立任务。
- D3（G5）：快照机制维持 PR-S1 已落地实现（manifest + workspace 外存储），
  不切换为设计稿的 git stash 方案。
- D4（G5）：安全平面代码落 `lion_code/tooling/`（Kernel 工具子系统），
  "禁止进入"的对象修正为 Agent Runtime 层 / MetaAgent / Capability SPI；
  spec 与架构测试期望值同步更新。
- D5（YAGNI 削减，用户已决）：不建 S5 谓词引擎与 shadow 迁移——现有规则
  解析器（`_matches_rule` 前缀/等值匹配）+ capabilities 判定 + S3 白名单已
  覆盖其全部事实表达；S5 缩为 R3 三件事。未来现有规则格式真不够表达时再立项。
- D6（YAGNI 削减，用户已决）：v1 redact-only，secret 注入延后——注入是能力
  不是防护，T1 闭环不依赖它；且子进程已继承父 env。注入随专用工具一起立项。
- D7（YAGNI 削减，用户已决）：白名单方向维度延后——v1 唯一 Level A 出口
  只产生 fetch 事实，方向列无消费者；S4 或专用工具落地时再加。
- D8（YAGNI 削减，用户已决）：优雅停机不做 git commit——权限层不触发
  workspace mutation（身份/rebase 中间态/自己管自己）；只发结构化停机信号，
  进度保存归 Supervisor 平面。

## Out of Scope

- S4 Sandbox（network namespace / 强制 proxy）——Level B 的完整阻断能力，
  另立任务，由残余风险登记表立项。
- S5 谓词引擎 / shadow 迁移 / 新规则 DSL（D5）。
- secret 注入（SecretRef / run_shell secrets 参数 / execution env 注入，D6）。
- git / publish / deploy 专用工具（T3 参数级事实源）——待审计数据证明需要后
  立项（与 D6 的注入同期）。
- 白名单方向维度与审计 direction 字段（D7）。
- 优雅停机中的进度 commit（D8）。
- MCP / Browser 出口组件——MCP 已移除，无浏览器工具。
- 历史对话 secret 清洗（已进上下文无法追回，如实声明）；
  secret 自动发现 / keychain 源（登记为残余风险，不实现）。
- 快照机制替换（维持 PR-S1 已落地的 manifest + 外部存储实现）。
