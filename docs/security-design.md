# Lion-Code 权限与安全设计（定稿）

本文件是安全平面的设计定稿，记录决策与理由；可执行契约见
`.trellis/spec/backend/` 下的 `tool-runtime-recovery.md`（PR-S1）、
`secret-boundary.md`（PR-S2）、`egress-guard.md`（PR-S3）。

## 1. 设计立场

Lion-Code 的 Agent 面向长时程自主运行（夜间任务、无人值守）。本设计
不以"动作是否危险"为尺子，而以"伤害是否可逆"为唯一尺子：

- **可逆伤害用恢复**：工作区受 Git/快照管理，本地文件状态皆可恢复
  （PR-S1），恢复不设限。
- **不可逆伤害用预防**：只有不可逆伤害进入硬边界，防护模式仍是预防。

系统里没有任何组件需要"理解"或"预测"风险：授权层只做机械谓词查表，
审计层只记录不干预，人类的预测权集中在配置时（白名单与规则）。

## 2. 威胁模型、信任域与对手模型

### 不可逆伤害

| 编号 | 伤害 | 对应窄腰 |
|---|---|---|
| T1 | Secret 离开信任域（含进入模型上下文——上下文会发往 Provider） | Secret Boundary + Egress Guard |
| T2 | 内部数据离开信任域 | Egress Guard |
| T3 | 外部系统状态被改变（发布、删云资源） | Authorization（命令级 best_effort） |

### 信任域（显式声明）

**信任域 = { 本机 + LLM Provider }。**

- Provider 流量不设卡：Agent 读过的源码本就随上下文发往 Provider，
  这是使用 LLM 的前提而非违规。
- T1/T2 防护的对象是"经 Agent 工具出口去向第三方目的地"。
- 若某部署的威胁模型不信任 Provider，本设计整体不适用，需换方案。

### 对手模型：prompt injection

Agent 会读取互联网内容（web_fetch），注入是主要对手。逐通道过检：

| 注入试图达成的 | 防护 | 强度 |
|---|---|---|
| 本地文件破坏 | PR-S1 快照无条件恢复 | 成立 |
| 外传已登记 secret | Level A 拦截（含 GET query）；Level B 观测 | A 可承诺 / B 尽力 |
| 内部数据发往非白名单目的地 | Level A 阻断 | 可承诺（进程内出口） |
| 经 shell 子进程外传（curl 等） | Level B 仅观测审计 | 尽力（S4 立项依据） |
| T3 发布/部署类操作 | 危险规则 + publish 前缀 → confirm / 停机 | best_effort（字符串事实） |
| 预算外动作 | 有人值守 confirm；无人值守优雅停机 | 成立 |

## 3. 窄腰总览

| 窄腰 | PR | 承诺 | 位置 |
|---|---|---|---|
| Workspace Snapshot | PR-S1（已落地） | workspace 状态可恢复 | pre 相无条件快照 |
| Secret Boundary | PR-S2（已落地） | 对**已登记** secret：值不进模型可见空间，输出全量 redact | post 相首位 |
| Egress Guard | PR-S3（已落地） | Level A 可承诺 / Level B 尽力 | pre 相 Permission 后 |
| Authorization 收尾 | PR-S5（已落地） | 预授权 + 预算外停机 + 授权快照 | 既有 Permission 平面 |
| Audit | PR-S1 起持续 | append-only 事实记录 | post 相末位 |

执行管线（`lion_code/tooling/`）：

```
pre ：Cancellation → WorkspaceSnapshot → PreToolHook → Permission → EgressGuard
执行：tool（含异常路径——异常结果同样过 post 链）
post：OutputSanitizer → ReadFreshness → ResultPolicy → Audit
```

## 4. 关键决策记录

- **G1 修正**：sanitizer 挂"全部工具输出进上下文"的统一入口（post 链首位，
  先于 ResultStore 与审计），而非仅 executor stdout；运行时异常转化的
  结果同样过链（封堵自定义工具异常消息旁路）。
- **G5 修正**：快照机制维持 PR-S1 落地实现（manifest + workspace 外存储），
  不用 `git stash create`（悬空提交会被 gc 回收）。安全代码落
  `lion_code/tooling/`（Kernel 工具子系统）；"禁止进入"的对象是
  Agent Runtime 层 / MetaAgent / Capability SPI，而非 Kernel 本身。
- **审计通道自身在防护面内**：审计参数序列化前做指纹 redact，
  `command_or_args` 不得成为明文 secret 聚集地。

## 5. 授权模型

- **预授权**：PermissionMode（default / acceptEdits / bypassPermissions /
  dontAsk）+ settings 规则（allow/deny，支持 `run_shell(前缀*)` 机械匹配）
  构成开工前的一次性授权。授权声明在会话启动时以 `session-grant` 行
  入审计（mode + 规则摘要指纹）——事后区分"Agent 越权"与"人类授权过
  但结果不好"的依据。
- **预算外**：人类没预见的动作，机器不替人类决定。有人值守 → 实时
  confirm（会话内确认缓存）；dontAsk/无人值守 → **优雅停机**：结构化
  budget_exceeded ToolResult（触发原因 + 挂起说明）+ `terminate` 停止
  循环 + 审计 blocked 行。不做 git commit——进度保存/恢复归 Supervisor
  平面，权限层不触发 workspace mutation。
- **不建谓词引擎（D5）**：现有规则格式 + capabilities 判定 + S3 白名单
  已覆盖全部机械事实表达；语义动作名只作审计标签。

## 6. 残余风险登记表

| # | 残余风险 | 缓解 / 升级路径 |
|---|---|---|
| R1 | 未登记 secret（硬编码在源码/日志里的凭证）无指纹、无感通过 | 显式接受；发现完整性属 scanner 信号层（未实现），有事故数据再立项 |
| R2 | secret 的非常规变换（percent-encoded、分片重组）可躲过指纹族 | 变体按审计证据逐个追加（常数成本） |
| R3 | shell 子进程网络对应用层不可见（curl 直传、DNS 隧道） | Level B 观测审计；完整阻断依赖 **S4 Sandbox**（network namespace / 强制 proxy），本表即其立项依据 |
| R4 | T3-via-shell 仅字符串匹配（`bash -c`、脚本间接调用可绕过） | best_effort 如实标注；git/publish 专用工具（参数级事实源）待审计数据立项 |
| R5 | 非 UTF-8 字节输出经 `errors=replace` 后指纹失配 | 显式接受 |
| R6 | `bypassPermissions` 的 allow-all 语义 | 人类的显式选择，信任域内；审计仍记录 |
| R7 | 工具流式 partial（on_update）仅本地终端显示 | 不进模型上下文与 Provider 负载 |
| R8 | 密钥与指纹文件位于 workspace 外但 shell 可读，可离线验证猜测 | 缓解：读取它们的命令输出会经 sanitizer（值本身无指纹不 redact，但读取行为入审计）；深度缓解依赖 S4 |
| R9 | 白名单质量是人因风险（预测权在配置时） | Level B 审计驱动加白；session-grant 行记录授权时的规则摘要 |

## 7. 削减决策（YAGNI，D1-D8）

| 决策 | 内容 | 再立项触发条件 |
|---|---|---|
| D1 | 白名单最小信任 deny-by-default，初始仅 provider 端点派生 | —（常态运行） |
| D5 | 不建谓词引擎与 shadow 迁移 | 现有规则格式无法表达新机械事实时 |
| D6 | v1 redact-only，secret 注入延后 | git/publish 专用工具立项时一并交付 |
| D7 | 白名单方向维度延后 | 出现第二个方向产生型事实源（S4 / 专用工具） |
| D8 | 优雅停机不做 commit | Supervisor 平面实现 checkpoint-resume 后自然归位 |

## 8. 架构门禁

见 `docs/advanced-capability-guide.md` 附：架构门禁第二条——
ToolRuntime 是工具调用的唯一路径，新工具不得绕过 sanitizer / egress /
权限判定；新的应用层网络出口必须接入 Level A 或显式标注 best_effort
并登记残余风险。
