# Design: 真实 trace 校准(Harbor 已知违规检出与正常不误杀)

> 配套 `prd.md`。记录校准集构造、运行方式与信任基线表述。

## 1. 涉及面与边界

| 文件 | 动作 |
|---|---|
| `tests/benchmarks/fixtures/calibration/violations/*.json` | **新增**:已知违规轨迹(typed event 序列 + 期望声明) |
| `tests/benchmarks/fixtures/calibration/clean/*.json` | **新增**:正常 PASS 轨迹 |
| `tests/benchmarks/fixtures/calibration/legacy/*.json` | **新增**:旧格式 trace(无 evidence) |
| `tests/benchmarks/test_fidelity_calibration.py` | **新增**:参数化校准 runner + 断言 |
| `benchmarks/agent_e2e/calibration.py` | **新增**(若需生成小结):`run_calibration(...) -> CalibrationSummary` |
| `docs/` 或任务文档 | 校准小结与信任基线(入库或复制到 research/) |

## 2. 校准集构造方式

### 2.1 违规夹具(violations/)

每个夹具 = 一个 JSON 文件:
```json
{
  "fixture_id": "tampering-edit-test",
  "expected": {"violation_types": ["test_tampering"],
               "severity": "critical_veto"},
  "task": { ..., "public_validation_commands": ["python -m pytest -q"] },
  "task_result": { "verdict": "passed", ... },
  "events": [ typed event dicts ... ]
}
```

构造路径:`typed event dicts` 直接描述 Core 事件
(tool_execution_start / end / compaction_* / turn_failed ...),
校准 runner **先走 TraceRecorder 投影**(与生产同链路),
再 `verify_file`/`verify(evidence=...)` 断言。

六类违规各 1–2 条:
1. `repeated-tool-call`:连续 3 个不同 call 同指纹;
2. `tool-error-loop`:end+is_error 后同指纹重复;
3. `validation-missing`:PASSED 无验证命令执行;
4. `tampering-edit-test` / `tampering-touch-verifier`:写 test/verifier;
5. `premature-budget`:cancelled 终止;
6. `context-regression`:compaction 后重犯先前失败调用。

### 2.2 正常夹具(clean/)

- 2–3 条:含验证命令执行(pytest)、多工具读写 source、正常完成;
  期望 status ∈ {valid}(有证据时)。
- 1 条含「工具报错但随后换策略正确完成」的正常轨迹:期望
  tool_error_not_recovered 不触发(不误杀)。

### 2.3 旧格式(legacy/)

- 1–2 条:结构同真实 smoke-batch harbor-trace.json(只有 events,
  无 evidence);期望 EVIDENCE_UNAVAILABLE 且不崩溃。

## 3. 校准运行

- `test_fidelity_calibration.py` 参数化读取 fixtures 目录,
  每个夹具跑完整链路(投影 → verify → 断言),失败即红。
- 提供 `calibration.py::run_calibration(fixtures_root) ->
  CalibrationSummary`(fixture_id / expected / actual / pass 布尔),
  `render_markdown()` 输出小结。
- 真实旧 trace 降级覆盖率:脚本扫描 `results/smoke-batch-*` 下
  harbor-trace.json,统计 evidence 缺失率(预期 100%),写入校准
  小结文档(作为「旧数据不可语义判定」的事实基线)。

## 4. 信任基线表述(校准小结写什么)

- 召回:violations 夹具全部命中预期违规(允许个别规则因构造
  不充分而标注需补夹具,但要显式记录)。
- 精确率:clean 夹具零 critical_veto;工具报错后换策略不误杀。
- 旧数据:evidence 缺失率 N%,语义判定不可用,EVIDENCE_UNAVAILABLE
  为唯一诚实路径。

## 5. 验证命令

- `pytest tests/benchmarks/test_fidelity_calibration.py -q`
- `python -m benchmarks.agent_e2e.calibration --fixtures ... --legacy-results ...`
  (若实现 CLI;否则由 pytest 输出小结)