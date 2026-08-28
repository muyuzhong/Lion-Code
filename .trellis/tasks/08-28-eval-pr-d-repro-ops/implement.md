# Implement:评测链 PR D(分析可复现与运维)

> 配套 `prd.md` / `design.md`。按序执行;每步完成即核对,进入下一步前
> 工作区干净(仅本任务改动)。

## 0. 前置

- 分支:从 `master` 新建 `eval-pr-d-repro-ops`(master 当前
  `b5bb677`,PR C 已合并)。
- 事实锚点:本机 `benchmarks/agent_e2e/results/smoke-flask-5014/` 含
  harbor-home(372K)/hf-home(15M)/xdg-cache(1.4M)与历史 run-* 目录;
  docker 镜像含 `swebench/sweb.eval.x86_64.pallets_1776_flask-5014:
  latest`。

## 1. P1-4 采样(models.py + deepeval_analysis.py)

- [ ] 1.1 models.py `DeepEvalMetricResult` +`samples`/`score_min`/
  `score_max` 与 validator(design 2.1);`DeepEvalMetricFixture`
  同步可选字段。
- [ ] 1.2 deepeval_analysis.py:签名透传 `judge_samples`
  (analyze_deepeval_case/analyze_verified_report,默认 3);采样循环
  逐样本(deadline 内);新增 `_metric_result_from_samples`(design 2.2;
  全失败/部分失败/单样本路径)。
- [ ] 1.3 parse_deepeval_analysis 透传 fixture 新字段。
- [ ] 1.4 verified_runner.py:`deepeval_samples: int = 3` +
  `_validate_request`(≥1)+ 传参。
- [ ] 1.5 cli.py verified 命令 `--deepeval-samples`(default 3)。
- [ ] 1.6 report.py 指标行采样渲染(design 2.5)。

## 2. P2-2 清理脚本

- [ ] 2.1 `scripts/benchmarks/verified-smoke/cleanup_smoke.sh`(design
  3.1/3.2):路径推导 + 守卫 + 缓存删除 + IMAGES 分支 + DRY 分支 + 摘要。
- [ ] 2.2 `bash -n` 通过;脱敏自查(grep `/home/`、`muyuzhong`、密钥)。

## 3. P2-3 寻迹数据库

- [ ] 3.1 `benchmarks/agent_e2e/digest_ledger.py`:DigestLedgerEntry +
  DigestLedger(append/lookup/count + 敏感键校验 + preview 统一
  redact_text;design 4.1/4.2)。
- [ ] 3.2 verified_runner.py:`digest_ledger_path` 字段 +
  `_write_digest_ledger` 勾挂(design 4.3,失败仅警告)。
- [ ] 3.3 cli.py `digest-lookup` 命令(design 4.4,三态退出码)。
- [ ] 3.4 run_smoke.sh:`--deepeval-samples "${DEEPEVAL_SAMPLES:-3}"`
  与 `--digest-ledger "$LEDGER_FILE"`(LEDGER_FILE 默认
  `$RESULT_ROOT/digest-ledger.jsonl`,`SMOKE_LEDGER_FILE` 可覆写)。

## 4. 模板与文档

- [ ] 4.1 `smoke.env.example`:可选注释 `DEEPEVAL_SAMPLES`(默认 3)。
- [ ] 4.2 `scripts/benchmarks/verified-smoke/README.md`:env 表补
  DEEPEVAL_SAMPLES/SMOKE_LEDGER_FILE;新增"残留清理"与"digest 寻迹"
  小节。
- [ ] 4.3 `docs/agent-e2e-verified-run.md`:"judge 多次采样"小节;
  "运行残留清理"与"digest 寻迹"小节(design 5)。
- [ ] 4.4 脱敏自查:`grep -rnE "/home/|muyuzhong|sk-[A-Za-z0-9]{16,}"
  scripts/benchmarks/verified-smoke/` 无命中。

## 5. 测试

- [ ] 5.1 `test_eval_analysis_observability.py`:采样聚合四类断言
  (design 6);既有 calls 断言更新为 3 轮样本顺序。
- [ ] 5.2 `test_verified_contracts.py`:validator 用例 + fixture
  透传。
- [ ] 5.3 `test_verified_cli_composition.py`:`--deepeval-samples 1`
  单样本路径 + md 采样断言 + digest-lookup 三态(经 CLI main)。
- [ ] 5.4 新增 `tests/benchmarks/test_digest_ledger.py`。
- [ ] 5.5 新增 `tests/benchmarks/test_smoke_cleanup.py`。
- [ ] 5.6 `test_smoke_template_guard.py`:TEMPLATE_FILES 增
  cleanup_smoke.sh。
- [ ] 5.7 targeted:
  `python3 -m pytest -q tests/benchmarks/test_eval_analysis_observability.py
  tests/benchmarks/test_verified_contracts.py
  tests/benchmarks/test_verified_cli_composition.py
  tests/benchmarks/test_digest_ledger.py
  tests/benchmarks/test_smoke_cleanup.py
  tests/benchmarks/test_smoke_template_guard.py`
- [ ] 5.8 回归:`tests/benchmarks/test_verified_execution_chain.py
  tests/benchmarks/test_trace.py tests/benchmarks/test_evaluation_cli.py`
- [ ] 5.9 门禁:`python3 -m compileall -q benchmarks/agent_e2e
  tests/benchmarks`;`git diff --check`;ruff format/check 无新指纹
  (按 CI 口径 `lion_code tests scripts`,触碰的测试文件须
  format-clean)。

## 6. 收尾

- [ ] 6.1 实施后勾销:`improvements-backlog.md` 勾选 P1-4/P2-2/P2-3。
- [ ] 6.2 提交(不 push):
  - `feat(benchmark): judge 多次采样取均值±范围并标注采样次数`
    (models/deepeval_analysis/verified_runner/cli/report)
  - `feat(benchmark): 运行残留一键清理脚本与 digest 寻迹数据库`
    (cleanup_smoke.sh、digest_ledger.py、verified_runner/cli 相关)
  - `docs(benchmark): 采样/清理/digest 寻迹文档`(docs + README +
    smoke.env.example + run_smoke.sh)
  - `test(benchmark): 采样聚合、cleanup 与 digest 寻迹测试`
    (tests/benchmarks/*)
- [ ] 6.3 核对 task.json(branch/base_branch 已设)。
- [ ] 6.4 开 PR(push + gh),CI 通过后合并;A5 本机复跑单题闭环
  (报告采样均值±范围 + ledger 可反查 + cleanup 干跑/实跑验证),
  复核后归档任务并回填 notes。

## 风险与回滚

- 采样默认 3 次使 A5 成本 ≈ ×3(约 0.45 USD):若 deadline 内无法
  完成 9 次调用,部分样本 TIMEOUT → 报告 reason 标注,语义不变。
- 既有测试对 judge.calls 顺序敏感:统一改为"指标外层、样本内层"
  顺序并在文档/测试注释注明。
- ledger 属追加写,旧文件格式演化:header 行含 schema_version,
  未来变更可检测;本 PR 不兼容旧格式文件(不存在历史文件,零包袱)。
- 任一阶段失败:回退仅限本任务文件;不改判定链与退出码语义。