# Implement:评测链 PR C(评分语义化)

> 配套 `prd.md` / `design.md`。按序执行;每步完成即核对,进入下一步前
> 工作区干净(仅本任务改动)。

## 0. 前置

- 分支:从 `master` 新建 `eval-pr-c-score-semantics`(master 当前
  `4abfea7`,PR A/B 已合并)。
- 已确认事实:A5 报告 `run-flask-5014-20260828-161826` 即 P2-1 分歧
  场景(harbor verifier_outcome=failed / reward 0.0,harness resolved
  =true),可作 A4/A5 复核锚点。

## 1. 数据模型(models.py)

- [ ] 1.1 `DeepEvalMetricResult` 增 `threshold: float | None = None`
  (ge=0,le=1)与 `threshold_met: bool | None = None`;validator:两者
  同存同缺;齐备时 `threshold_met == (status COMPLETED and score is
  not None and score >= threshold)`(design 2.1)。
- [ ] 1.2 新 `DeepEvalScoreGate`(passed/passed_metrics/
  evaluated_metrics/reason + validator,design 2.2)。
- [ ] 1.3 `DeepEvalAnalysis` 增 `agent_model`、`judge_fingerprint`、
  `score_gate` 三个可选字段(design 2.3)。
- [ ] 1.4 核对:旧报告 JSON 可 `model_validate`(additive);SCHEMA_VERSION
  不变。

## 2. 分析组合(deepeval_analysis.py)

- [ ] 2.1 新增 `DEEPEVAL_METRIC_THRESHOLDS` 常量(三指标均 0.5,
  design 3.1)并加入 `__all__`。
- [ ] 2.2 `_metric_result_from_observation` 填充 threshold/threshold_met
  (design 3.2,唯一填充点)。
- [ ] 2.3 `parse_deepeval_analysis` 指标循环同样按名补齐(design 3.3,
  fixture schema 不动)。
- [ ] 2.4 `_analysis_from_metrics` 计算 `score_gate`(design 3.4);
  `_unavailable_analysis` 透传新身份字段、score_gate 为 None。
- [ ] 2.5 `analyze_deepeval_case` 与 `analyze_verified_report` 增加
  `agent_model`/`judge_fingerprint` 参数(默认 None)并贯通到结果模型。

## 3. SDK metric 构造(deepeval_metrics.py)

- [ ] 3.1 `build_deepeval_metrics` 的 `threshold=None` 改为从
  `DEEPEVAL_METRIC_THRESHOLDS` 取各指标阈值(design §(导入自
  deepeval_analysis,无环:deepeval_analysis 仅函数内懒加载
  DeepEvalSdkJudge))。

## 4. runner(verified_runner.py)

- [ ] 4.1 `_run_post_processing`:计算 `agent_model` 与
  `judge_fingerprint = _judge_fingerprint(judge_model)`(sha256 于
  `"{model}\n{LITELLM_API_BASE或空}"`),传入 `analyze_verified_report`。
- [ ] 4.2 `_analysis_failure` 增 agent_model/judge_fingerprint 参数并
  写入结果。

## 5. 报告渲染(report.py)

- [ ] 5.1 DeepEval 段:模型行加 Agent 模型/Judge 模型/Judge 指纹;
  指标行加 `(阈值 x,达/未达)`;段末加"门禁结论"行(design 6.1/6.2)。
- [ ] 5.2 `_harbor_harness_divergence(report)` + harness 段后渲染
  "分歧标注"行(design 6.3)。

## 6. 模板与文档

- [ ] 6.1 `run_smoke.sh`:必填循环追加 `DEEPEVAL_JUDGE_MODEL`;
  verified-run 调用传 `--deepeval-judge-model "$DEEPEVAL_JUDGE_MODEL"`;
  头部注释同步。
- [ ] 6.2 `smoke.env.example` 增 `DEEPEVAL_JUDGE_MODEL`(分组注释,
  值空)。
- [ ] 6.3 `scripts/benchmarks/verified-smoke/README.md`:env 表 + 说明。
- [ ] 6.4 `docs/agent-e2e-verified-run.md` 增三小节:"judge 独立配置与
  指纹"、"评分阈值与门禁语义"、"Harbor 与官方结果分歧"(design 7)。
- [ ] 6.5 脱敏自查:`grep -rnE "/home/|muyuzhong|sk-[A-Za-z0-9]{16,}"
  scripts/benchmarks/verified-smoke/` 无命中;`bash -n` 通过。

## 7. 测试

- [ ] 7.1 `test_eval_analysis_observability.py`:design 8 节点(全过/
  部分/全超时/partial/身份字段)。
- [ ] 7.2 `test_verified_contracts.py`:模型 validator 与 fixture 补齐
  断言。
- [ ] 7.3 `test_verified_cli_composition.py`:md 新行断言 + 分歧/一致
  两场景。
- [ ] 7.4 `test_smoke_template_guard.py`:ENV_FILE_CONTENT 加
  DEEPEVAL_JUDGE_MODEL;新增缺失该变量用例。
- [ ] 7.5 运行 targeted:
  `python3 -m pytest -q tests/benchmarks/test_eval_analysis_observability.py
  tests/benchmarks/test_verified_contracts.py
  tests/benchmarks/test_verified_cli_composition.py
  tests/benchmarks/test_smoke_template_guard.py`
- [ ] 7.6 回归:`python3 -m pytest -q tests/benchmarks/test_verified_execution_chain.py
  tests/benchmarks/test_verified_cli_composition.py tests/benchmarks/test_trace.py`
- [ ] 7.7 门禁:`python3 -m compileall -q benchmarks/agent_e2e
  tests/benchmarks`;`git diff --check`;ruff format 消除新文件指纹
  (若 CI 报格式差异则 `ruff format` 三个新触碰 py 文件后重跑 7.5)。

## 8. 收尾

- [ ] 8.1 实施后勾销:`improvements-backlog.md` 勾选 P1-3/P1-5/P2-1。
- [ ] 8.2 提交(中文 message,按改动性质分组;不 push):
  - `feat(benchmark): judge 独立配置与指纹记录,评分阈值与门禁语义`
    (models.py/deepeval_analysis.py/deepeval_metrics.py/verified_runner.py)
  - `feat(benchmark): 报告渲染阈值门禁结论与 Harbor/官方分歧标注`
    (report.py)
  - `docs(benchmark): judge 独立配置与评分门禁/分歧语义文档`
    (docs + verified-smoke/README + smoke.env.example + run_smoke.sh)
  - `test(benchmark): 评分阈值门禁、分歧标注与模板 judge 变量测试`
    (tests/benchmarks/*)
- [ ] 8.3 更新 task.json:`branch=eval-pr-c-score-semantics`、
  `base_branch=master`(create 已设置,核对)。
- [ ] 8.4 开 PR(push 分支 + `task.py create-pr` 或 gh),CI 通过后
  合并;A5 本机复跑单题闭环(带 `DEEPEVAL_JUDGE_MODEL` 显式值),报告
  复核新字段/门禁结论/分歧标注;归档任务并回填 notes。

## 风险与回滚

- 旧报告 JSON 兼容:全部新字段带默认值,`model_validate` 向后兼容;
  若 CI 中 fixture 断言依赖指标行格式,属测试应改文案而非语义。
- 模板新增必填变量:本地 `smoke.env`(gitignore)需补
  `DEEPEVAL_JUDGE_MODEL`,否则 rc=2——验收即此行为。
- 任一阶段失败:回退仅限本任务文件;不改既有判定链与退出码语义。