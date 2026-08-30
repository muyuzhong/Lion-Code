# Implement: 真实 trace 校准(Harbor 已知违规检出与正常不误杀)

> 配套 `prd.md` / `design.md`。前置:子任务一(evidence)+ 子任务二
> (verifier rewrite)已合并。

## 0. 前置

- 分支:从 `eval-verifier-rewrite`(或 master 合入后)新建
  `eval-fidelity-calibration`。
- 确认 `benchmarks/agent_e2e/results/smoke-batch-*` 下真实
  harbor-trace.json 数量与结构(已勘察:13 条,246 个 tool end)。

## 1. 校准夹具

- [ ] 1.1 `tests/benchmarks/fixtures/calibration/violations/`:
      六类违规各 1–2 条(design 2.1),typed event dicts + 期望。
- [ ] 1.2 `tests/benchmarks/fixtures/calibration/clean/`:
      2–3 条正常 PASS(含验证命令);1 条「报错后换策略」不误杀。
- [ ] 1.3 `tests/benchmarks/fixtures/calibration/legacy/`:
      1–2 条旧格式(无 evidence)。

## 2. 校准 runner

- [ ] 2.1 `benchmarks/agent_e2e/calibration.py`:
      `CalibrationCase` / `CalibrationSummary` /
      `run_calibration(fixtures_root)` / `render_markdown()`。
- [ ] 2.2 链路:typed event dicts → TraceRecorder(投影)→
      verify(evidence) → 断言 expected。<br>
      注意:Event dicts 需经 `_event_payload` 兼容(与 TraceRecorder.record
      实际输入一致,直接用 event 类实例最稳)。
- [ ] 2.3 legacy 断言:EVIDENCE_UNAVAILABLE 且不崩溃。
- [ ] 2.4 旧真实 trace 扫描脚本:统计 evidence 缺失率,输出到小结。

## 3. 测试与断言

- [ ] 3.1 `tests/benchmarks/test_fidelity_calibration.py`:参数化读取
      fixtures,逐条断言(violations 命中 / clean 零 veto /
      legacy 降级)。
- [ ] 3.2 校准小结 Markdown 入库:如
      `benchmarks/agent_e2e/results/calibration-summary-<date>.md`
      (或任务 research/),含召回/精确率/旧数据降级率。

## 4. 验证

- [ ] 4.1 `pytest tests/benchmarks/test_fidelity_calibration.py -q` 全绿。
- [ ] 4.2 `pytest tests/benchmarks -q` 全绿(环境性失败除外)。
- [ ] 4.3 ruff check。

## 5. 提交

- [ ] 5.1 单次提交:
      `test(benchmark): 过程判定校准集——已知违规检出/正常不误杀/旧 trace 降级,信任基线入库`。

## 6. 后续钩子

- 校准发现的规则缺陷回写子任务二(如 marker 名单、阈值、scope
  分类规则),循环直至全绿。