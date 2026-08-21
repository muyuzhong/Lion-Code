# 权限与安全平面落地（PR-S2 / S3 / S5）

## Goal

在已落地的 PR-S1（快照 / 审计 / 回滚）之上，交付安全设计剩余的三个窄腰：
Secret Boundary（PR-S2）、Egress Guard（PR-S3）、Authorization Policy（PR-S5），
使 Agent 获得无人值守长任务所需的预授权自主能力，同时封死三类不可逆伤害
（T1 secret 泄漏、T2 内部数据外传、T3 外部系统状态改变）中当前可防护的路径。
设计文本本身按第一性原理审核的 G1-G7 修正定稿，落地为 `docs/security-design.md`。

核心纪律（来自审核定稿）：机械谓词、零意图理解；承诺强度匹配事实质量；
A/B 双层诚实承诺；信任域显式声明为 {本机 + LLM Provider}。

## Background

- 设计方案与审核（G1-G7 缺口）已在前一会话完成：
  - G1 sanitizer 必须挂"全部工具输出进上下文"统一入口（非仅 executor stdout）；
  - G2 信任域需显式声明，MCP server 归 Level B（本项目 MCP 已移除，无对象）；
  - G3 授权谓词按事实源分级：参数级事实 guaranteed、命令字符串事实 best_effort；
  - G4 egress 事实必须有方向维度（fetch 与 push/upload 分离）；
  - G5 目录/分层/快照机制与已落地 PR-S1 对齐，不用 `git stash create -u`；
  - G6 补对手模型（prompt injection）与残余风险登记表；
  - G7 secret 闭环措辞弱化为"对已登记 secret 闭环"。
- 实施顺序遵循设计稿：Secret Boundary 先行（S3 的 payload 扫描复用其指纹族），
  Egress Guard 先于 Authorization 上线（缺位期 fallback = block + audit）。

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
   设计稿中 MCP/Browser 出口组件在本项目无对象，Level A 收窄为 web_fetch。
4. 执行缝：`CommandExecutionBackend` 协议 + `LocalCommandExecutionBackend`
   （`lion_code/tooling/execution.py:11`）是 secret env 注入点（值直达子进程）。
5. 权限面已有骨架：`lion_code/tooling/permission.py`（PermissionPolicy 的
   allow/deny 规则解析、`is_dangerous` 硬边界、PermissionDecision 三态
   allow/deny/confirm）、`PermissionMiddleware`（`lion_code/tooling/middleware.py:145`）、
   `lion_code/permission_state.py`（PermissionMode：
   default / acceptEdits / bypassPermissions / dontAsk + 确认缓存）。
   S5 在此之上扩展，旧 allow/deny 规则降级 shadow 观察后删除。
6. 有人/无人值守信号：TUI 交互模式与 `--web` 服务模式（`lion_code/__main__.py:44`）
   可区分；PermissionMode 的 dontAsk 语义可承载"预算外 → 优雅停机"分支。
7. 分层归属：`tooling/` 属 Kernel（`.trellis/spec/backend/four-layer-ownership.md:10`）。
   安全平面代码落 `lion_code/tooling/`；禁止进入的是 Agent Runtime 层
   （runtime/ 会话与对话状态）、MetaAgent、Capability SPI。
   设计稿 §六 的"禁止进入 Kernel"表述按此修正。
8. T3 无参数级事实源：无 git/publish/deploy 专用工具，git 操作走 run_shell ——
   v1 的 T3 谓词只能基于命令字符串，须标 best_effort（G3），
   专用工具 deferred（见 Out of Scope）。

## Requirements

### R1. Secret Boundary（PR-S2）

- SecretProvider：secret 三源（.env / 系统 keychain / 环境变量），v1 以 .env 为主；
  对模型只暴露 reference 元数据（名字、是否已配置）。
- 执行时注入：`CommandExecutionBackend.run` 启动子进程时按 `SecretRef` 注入 env，
  值不经模型可见空间。
- OutputSanitizer 为 post-phase middleware（G1 落点）：覆盖全部 7 个工具的输出
  （run_shell / read_file / grep_search / web_fetch 为重点路径）；
  分隔符切分（token / 行 / 引号界）+ HMAC 指纹族
  （原值 / base64 / hex / urlencode 派生）线性比对，命中原地替换 `***`；
  禁止全输出滑窗哈希。
- HMAC 密钥存 workspace 外；sanitizer 只持有指纹不持有明文。
- `sanitizer_hits` 计数入审计。

### R2. Egress Guard（PR-S3）

- Level A（guaranteed）：web_fetch 序列化点检查 `(destination, direction)` 白名单
  + payload 指纹扫描（复用 S2 指纹族）；白名单外 → block + audit
  （S4 缺位期 fallback，不发明临时确认机制）。
- Level B（best effort）：run_shell 命令字符串提取 URL/域名，比对白名单，
  审计行标注 `best_effort`；不做命令意图分析、不阻断。
- 白名单默认姿态（Q1 决策）：最小信任 deny-by-default，初始白名单仅含
  从 provider 配置派生的 endpoints；用户依 Level B 审计中的高频 destination
  在 settings 中加白（审计驱动演进）。
- 白名单含方向维度（G4）：fetch 与 push/upload 分离；github.com push、
  pypi.org upload 不因 destination 命中白名单而隐式放行，
  默认落入 require_confirmation。
- 信任域显式声明（G2）：{本机 + LLM Provider}，写入 `docs/security-design.md`
  与 `docs/advanced-capability-guide.md`。

### R3. Authorization Policy（PR-S5）

- 谓词词汇表只引用窄腰机械事实：workspace.mutation、
  egress.(destination, direction)、shell.command、工具参数；
  语义动作名仅作审计标签，永不参与判定。
- 事实源分级标注（G3）：参数级事实 guaranteed；命令字符串事实 best_effort。
- require_confirmation 接 PermissionMiddleware 现有 confirm 路径与确认缓存。
- 预算外 fallback：default 模式 → 实时确认；dontAsk / 无人值守 → 优雅停机
  （commit 当前进度 + handoff 报告 + 挂起），停机事件入审计。
- 任务启动时的授权声明快照入审计（责任归属依据）。
- 旧 allow/deny 规则先降级 shadow 模式（只记录不拦截），对照观察后删除。

### R4. 审计扩展

- ExecutionEvent（`lion_code/tooling/audit.py:20`）已有 destination、
  fingerprint_hit、authorization_source 字段；本任务补充 direction、
  sanitizer_hits、best_effort 标注；append-only、存 workspace 外，
  只记录不干预。

### R5. 设计定稿与门禁文档

- `docs/security-design.md` 按 G1-G7 修正定稿：信任域声明、快照机制对齐已落地
  实现、目录/分层修正、谓词事实源分级、egress 方向维度、闭环措辞弱化
  （"对已登记 secret 闭环，发现完整性是显式残余风险"）、对手模型与残余风险登记表
  （prompt injection 视角逐通道过检，作为 S4 Sandbox 立项依据）。
- `docs/advanced-capability-guide.md` 增加架构门禁：ToolRuntime 是工具调用唯一路径，
  新工具不得绕过 sanitizer / egress / authorization。

## Acceptance Criteria

- [ ] 注册 secret 在 run_shell / read_file / grep_search / web_fetch 任一输出中
      均被 redact（每条路径各一条测试）；secret 明文不出现在 provider 请求负载
      （测试断言）。
- [ ] web_fetch 请求白名单外 destination 被阻断并产生审计行；白名单内 fetch 放行；
      provider 流量不受 Egress Guard 影响。
- [ ] run_shell 命令字符串含 URL 时，审计行含 best_effort 标注与提取的 destination。
- [ ] 谓词表判定：workspace.mutation 放行；push/upload 类目的地 require_confirmation；
      deny(secret.fingerprint_hit and egress.outbound) 生效。
- [ ] dontAsk 模式下预算外动作触发优雅停机：进度 commit + handoff 报告 + 审计行。
- [ ] 任务启动时的授权声明快照出现在审计中。
- [ ] 旧 allow/deny 规则在 shadow 模式下产生对照记录（新模型判定与旧规则判定并排）。
- [ ] 架构测试期望值同步更新且全绿；本地质量门禁
      （ruff / mypy / 基线比对）通过；CI 绿。

## Key Decisions

- D1（Q1，用户已决）：Level A 白名单采用最小信任 deny-by-default，
  初始仅含配置派生的 provider endpoints，靠审计数据驱动加白演进。
- D2（G3）：v1 的 T3 谓词基于命令字符串并如实标注 best_effort；
  git/publish 专用工具（参数级事实源）待审计数据证明需要后另立任务。
- D3（G5）：快照机制维持 PR-S1 已落地实现（manifest + workspace 外存储），
  不切换为设计稿的 git stash 方案。
- D4（G5）：安全平面代码落 `lion_code/tooling/`（Kernel 工具子系统），
  "禁止进入"的对象修正为 Agent Runtime 层 / MetaAgent / Capability SPI；
  spec 与架构测试期望值同步更新。

## Out of Scope

- S4 Sandbox（network namespace / 强制 proxy）——Level B 的完整阻断能力，另立任务，
  由残余风险登记表立项。
- git / publish / deploy 专用工具（T3 参数级事实源）——待审计数据证明需要后立项。
- MCP / Browser 出口组件——MCP 已移除，无浏览器工具。
- 历史对话 secret 清洗（已进上下文无法追回，如实声明）；
  .env 三源之外的 secret 自动发现（登记为残余风险，不实现）。
- 快照机制替换（维持 PR-S1 已落地的 manifest + 外部存储实现）。
