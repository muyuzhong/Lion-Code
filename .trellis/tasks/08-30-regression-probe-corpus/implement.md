# Implement: Evidence Regression Corpus——regression_probe.py + evidence_regression_corpus.py

## 执行顺序

1. **process_verifier.py 扩展**:`ProcessReplayContext` + `verify_case`,
   内部 `_verify_shared` 抽取,`_validation_missing` / `_premature_termination`
   改为消费极简 context;`verify()` 行为不变。
2. **regression_probe.py 新建**:`probe_holds` + `minimize_failure_evidence`。
3. **evidence_regression_corpus.py 新建**:`EvidenceRegressionCase` +
   入库判定 + `EvidenceRegressionCaseStatus/Result` +
   `EvidenceRegressionCorpusReport` + `run_evidence_regression_corpus`。
4. **__init__.py 导出** 新符号。
5. **测试**:`tests/benchmarks/test_regression_probe.py`(5 条验收中 1/2/5
   的 probe 部分)、`tests/benchmarks/test_evidence_regression_corpus.py`
   (验收 3/4/5)。
6. **spec 更新**:`.trellis/spec/backend/agent-e2e-evaluation.md` 补充契约
   与「Evidence Regression Corpus ≠ Harness 行为回归」边界。
7. **验证**:targeted tests + compileall + git diff --check;再全量
   `pytest -q`(按 spec Section 6 要求,提交前跑全量)。

## 验证命令

```bash
.venv/bin/python -m pytest -q tests/benchmarks/test_regression_probe.py tests/benchmarks/test_evidence_regression_corpus.py tests/benchmarks/test_process_verifier.py tests/benchmarks/test_first_error.py
.venv/bin/python -m compileall -q lion_code benchmarks tests
git diff --check
```

## 提交

- 单 commit,中文 message:`feat(benchmark): Evidence Regression Corpus——单事件不可再约简的失败片段与检测规则回归语料`。
- 提交前复查 `git diff` 无无关改动。

## 回滚点

- 若 test_process_verifier 回归:先检查 `_verify_shared` 抽取是否改变
  verify() 聚合语义;回退到原 verify() 逻辑。
