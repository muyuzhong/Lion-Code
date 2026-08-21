# 实施计划

按依赖顺序交付四个 PR（每个 PR 一个职责，独立可回滚）。
S3 复用 S2 的指纹族，S5 复用 S3 的出口事实，docs 定稿在实现后如实落地。

## PR-S2 Secret Boundary

1. `secret_provider.py`：SecretStore（.env 解析 + 环境变量源；keychain defer）
   + SecretRef 元数据 + 指纹族预计算 + `~/.lion/sanitizer.key` 密钥管理。
2. `output_sanitizer.py`：OutputSanitizerMiddleware（分隔符切分 + 指纹比对
   + redact + hits 计数入 details）。
3. `execution.py`：run_shell `secrets` 参数 → 子进程 env 注入；
   `types.py` 同步工具 schema。
4. `agent_builder.py`：post 链首位插入 sanitizer；ToolBindings 开关。
5. `audit.py`：sanitizer_hits 字段。
6. 测试：四条 redact 路径各一条（run_shell / read_file / grep_search /
   web_fetch）；secret 明文不出现在 provider 请求负载（capture 断言）；
   指纹族四种变换覆盖；密钥文件权限。
7. spec：`.trellis/spec/backend/` 新增 secret-boundary 契约文档。

## PR-S3 Egress Guard

1. `egress_guard.py`：EgressWhitelist（(host, direction)）+ Level A pre 检查
   + URL 全串指纹扫描 + Level B run_shell URL 提取。
2. 白名单配置发现（home / cwd settings 模式）+ provider host 派生注入
   （composition root）。
3. `agent_builder.py`：pre 链 Permission 后插入；ToolBindings 开关。
4. `audit.py`：direction / best_effort 字段。
5. 测试：白名单外 block + 审计行；白名单内放行；provider 流量不受影响；
   run_shell URL 提取审计行（best_effort=true）；GET query 带指纹命中即阻断
   （deny(secret_hit and egress.outbound) 首次生效）。
6. spec 同步。

## PR-S5 Authorization Policy

1. `permission.py`：谓词表加载与机械判定 + 事实源分级标注 + 授权快照入审计。
2. dontAsk 优雅停机：结构化 budget_exceeded ToolResult + handoff 报告，
   替换 auto-deny 分支；模型可见通知走 ToolResult 回流。
3. shadow 对照：旧 allow/deny 并行判定只记录（notes.shadow_old）。
4. 测试：谓词判定矩阵（allow / require_confirmation / deny×组合谓词）；
   dontAsk 停机产物（进度说明 + handoff + 审计行）；授权声明快照；
   shadow 对照行。
5. spec / `docs/tui.md` 更新（dontAsk 语义变更）。
6. 观察期后删除旧规则判定路径（独立小 PR）。

## PR-docs 设计定稿

1. `docs/security-design.md` 按 G1-G7 修正定稿：信任域声明、快照机制对齐
   已落地实现、目录/分层修正、谓词事实源分级、egress 方向维度、闭环措辞
   弱化、prompt injection 对手模型 + 残余风险登记表（S4 立项依据）。
2. `docs/advanced-capability-guide.md` 门禁段落：ToolRuntime 唯一路径，
   新工具不得绕过 sanitizer / egress / authorization。
3. `tests/architecture` 期望值同步（若新增模块需登记）。

## 验证命令

- 本地快验：`PYTHONPATH=tests python -m unittest discover tests -p "test_*.py"`
- 推送前全套质量门禁（对照 `.github/workflows/ci.yml`，基线
  `docs/quality-baseline-2026-08.json`）：
  `python -m ruff check lion_code tests scripts --output-format=json > ruff.json
  && python scripts/check_quality_baseline.py ruff-check ruff.json --status 1
  --baseline docs/quality-baseline-2026-08.json`（format / mypy / radon /
  vulture 同理）。
- 架构门禁：`tests/architecture/*` 全量。
- PR CI：`gh run watch --exit-status`。

## 风险文件与回滚点

- `middleware.py` / `agent_builder.py`：链顺序敏感——sanitizer 必须 post
  首位（redact 先于 ResultStore / 审计），egress 在 Permission 之后。
- `permission.py`：dontAsk 语义变更；shadow 期间判定行为不变。
- `tools.py` `_web_fetch` 不改本体（检查全部在 middleware 层）。
- 回滚：ToolBindings 开关关闭即回现状；PR 级 revert（squash 单提交）。

## task.py start 前检查

- prd / design / implement 三件套齐备（本文件）。
- 架构测试登记清单确认：`tests/architecture` 中 tooling 树期望是否需要
  加入 secret_provider / output_sanitizer / egress_guard。
- implement.jsonl / check.jsonl：inline 工作流跳过策展门
  （Phase 2 经 trellis-before-dev 加载上下文）。
