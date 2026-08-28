# Implement:评测链 PR A(安全声明 + 保真度)

> 前置:`prd.md`、`design.md`、`research/*.md`。
> 分支名建议:`eval-fidelity-pr-a`(base `master`)。

## 0. 提交计划(原子提交×3)

1. `feat(benchmark): 轨迹事件补 toolName 映射与时间戳` — trace.py + 模型字段 + trace 测试;
2. `feat(benchmark): 离线分析投影过滤 message_update 并显式关停上报` — deepeval_analysis.py + 分析测试;
3. `docs(benchmark): 注明 DeepEval SDK 固定 view 提示为已知输出` — docs/agent-e2e-verified-run.md。

每步独立可回滚;PR 合并前跑 targeted tests + 真实重跑对比。

## 1. P1-1 trace.py + TraceEvent(先做,数据源头)

- [ ] `TraceEvent` 增加 `started_at: datetime | None = None`、
      `finished_at: datetime | None = None`(import `datetime`/
      `timezone`、`utc_now` from `.models`)。
- [ ] `record()`:`tool_name` 查找加 `"toolName"` 键;
      `_event_summary` selected keys 补 `"toolName"`。
- [ ] 新增 `_event_timestamps(payload) -> tuple[datetime, datetime]`:
      message.timestamp(ms)→ UTC;否则 `utc_now()`。
- [ ] `record_tool_call()` 同上填时间戳。
- [ ] 核对 `summary()`/`write_json()` 无字段遗漏(digest 自动含
      新字段)。

## 2. P1-2 + P0-1 deepeval_analysis.py

- [ ] `NOISE_EVENT_TYPES = frozenset({"message_update"})`;
      `build_deepeval_trajectory` 先滤后截。
- [ ] `DeepEvalTelemetryError(DeepEvalResultError)` +
      `_ensure_telemetry_off()`(env + `is_confident()` lazy import)。
- [ ] `analyze_verified_report` 入口先 `_ensure_telemetry_off()`;
      成功路径 `extensions["telemetry"] = "off"` 写回分析结果。
- [ ] `__all__` 同步导出新符号(如需要)。

## 3. 文档

- [ ] `docs/agent-e2e-verified-run.md`:注明 `deepeval view` / Confident
      共享建议为 SDK 固定文案;本评测链显式关停上报
      (`CONFIDENT_API_KEY` 拒绝)。

## 4. 测试

- [ ] `tests/benchmarks/test_trace.py`:toolName 映射、时间戳提取
      (message ms / 接收时刻)、既有脱敏断言不回归。
- [ ] `tests/benchmarks/test_eval_analysis_observability.py`:key 已设置
      拒绝(FAILED + reason)、未设置 COMPLETED +
      `telemetry=="off"`、`message_update` 过滤与事件数下降。
- [ ] 核对既有测试对 `TraceEvent` 构造/digest 断言的兼容。

## 5. 验证

- [ ] targeted:
      `.venv/bin/python -m pytest -q tests/benchmarks/test_trace.py
      tests/benchmarks/test_eval_analysis_observability.py
      tests/benchmarks/test_verified_contracts.py
      tests/benchmarks/test_verified_cli_composition.py`
- [ ] `python3 -m compileall -q benchmarks/agent_e2e` 与
      `git diff --check`。
- [ ] (可选,需评测主机)重跑 flask-5014 同题:轨迹带工具名/时间戳、
      投影事件数显著下降、日志无 "Posting the run anyway"、三指标
      分数非全 0 且 reason 引用工具名;对比指标分布不变。

## 6. 回滚点

- 提交 1 独立可回滚(数据源头);提交 2 依赖 1 的时间戳字段,
  回滚按提交序;文档提交无依赖。