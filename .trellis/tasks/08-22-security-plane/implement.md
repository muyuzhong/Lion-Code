# 实施计划（YAGNI 削减后：3 个 PR）

按依赖顺序交付。S3 复用 S2 的指纹族；S5-lite 足够小，与 docs 定稿合并为
一个 PR。每个 PR 一个职责，独立可回滚。

## PR-S2 Secret Boundary（redact-only）

1. `secret_provider.py`：SecretStore（.env 全量 + 进程 env 名字模式
   `*_KEY/*_TOKEN/*_SECRET/*_PASSWORD`）+ HMAC 指纹族（原值 + base64 两变体）
   + `~/.lion/sanitizer.key` 自动生成（0600）。
2. `output_sanitizer.py`：OutputSanitizerMiddleware（分隔符切分 + 指纹比对
   + redact + hits 计数入 details）。
3. `agent_builder.py`：post 链首位插入 sanitizer；ToolBindings 开关
   enable_secret_boundary。
4. `audit.py`：sanitizer_hits 字段。
5. 测试：四条 redact 路径各一条（run_shell / read_file / grep_search /
   web_fetch）；printenv 进程 env 凭据 redact；secret 明文不出现在
   provider 请求负载（capture 断言）；指纹两变体覆盖；密钥文件权限；
   token 切分边界（引号内含空格的 secret 值）。
6. spec：`.trellis/spec/backend/` 新增 secret-boundary 契约文档。

## PR-S3 Egress Guard

1. `egress_guard.py`：EgressWhitelist（host 集合）+ Level A pre 检查
   （host 白名单 + URL 全串指纹扫描）+ Level B run_shell URL 提取。
2. 白名单：provider host 派生注入（composition root）+ settings 加白条目
   （沿用 load_permission_rules 的 home / cwd 发现模式）。
3. `agent_builder.py`：pre 链 Permission 后插入；ToolBindings 开关
   enable_egress_guard。
4. `audit.py`：best_effort 字段。
5. 测试：白名单外 block + 审计行；白名单内放行；provider 流量不受影响；
   URL query 指纹命中即阻断；run_shell URL 提取审计行（best_effort=true）。
6. spec 同步。

## PR-S5-lite + docs 定稿（合并一个 PR）

1. `permission.py`：dontAsk 分支改优雅停机（结构化 budget_exceeded
   ToolResult + handoff 文本 + 审计行，不做 git commit）；
   push 类语境（git push / npm publish 等机械匹配）接入现有 confirm 路径。
2. 授权快照：会话启动时 mode + 规则摘要入审计。
3. `docs/security-design.md` 定稿：信任域声明、快照机制对齐已落地实现、
   目录/分层修正、egress A/B 承诺分层、闭环措辞弱化（"对已登记 secret
   闭环，发现完整性是显式残余风险"）、prompt injection 对手模型 +
   残余风险登记表（S4 立项依据）、D5-D8 削减决策记录。
4. `docs/advanced-capability-guide.md` 门禁段落：ToolRuntime 唯一路径，
   新工具不得绕过 sanitizer / egress / 权限判定。
5. `docs/tui.md` 与 `.trellis/spec/backend/` 更新（dontAsk 语义变更）。
6. `tests/architecture` 期望值同步（登记 secret_provider /
   output_sanitizer / egress_guard 模块）。
7. 测试：dontAsk 停机产物（结构化结果 + 审计行 + 无 commit）；
   push 语境 confirm 触发与缓存命中；授权快照记录。

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
- `permission.py`：dontAsk 语义变更。
- `tools.py` `_web_fetch` 不改本体（检查全部在 middleware 层）；
  `execution.py` 本任务不改（注入延后，D6）。
- 回滚：ToolBindings 开关关闭即回现状；PR 级 revert（squash 单提交）。

## task.py start 前检查

- prd / design / implement 三件套齐备（本文件）。
- 架构测试登记清单确认：`tests/architecture` 中 tooling 树期望是否需要
  加入 secret_provider / output_sanitizer / egress_guard。
- implement.jsonl / check.jsonl：inline 工作流跳过策展门
  （Phase 2 经 trellis-before-dev 加载上下文）。
