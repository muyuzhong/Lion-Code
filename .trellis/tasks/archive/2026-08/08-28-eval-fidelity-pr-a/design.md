# Design:评测链 PR A(安全声明 + 保真度)

> 前置阅读:`research/deepeval-confident-sdk.md`、
> `research/core-event-serialization.md`、`prd.md`。

## 1. 总览

三个改动点,顺序:`trace.py`(P1-1 数据源头)→ `deepeval_analysis.py`
(P1-2 投影过滤 + P0-1 入口检查)→ `verified_runner.py` 零改动
(检查失败自然落入 `_analysis_failure`),外加模型字段与测试。

## 2. P0-1 显式关停上报(design)

### 2.1 检查位置与行为

- 新增 `_ensure_telemetry_off()` 于 `deepeval_analysis.py`:
  1. `os.environ.get("CONFIDENT_API_KEY")` 非空 → raise
     `DeepEvalTelemetryError`(新异常,继承 `DeepEvalResultError`);
  2. 尝试 `from deepeval.confident.api import is_confident`,
     `ImportError`(SDK 未装)→ 直接通过(无上报能力);
     `is_confident()` 为真(settings 层有 key)→ 同样 raise。
- 调用点:`analyze_verified_report` 入口第一行
  (backlog 指定位置;两条调用路径——`verified_runner._run_post_processing`
  与 pytest 入口 `test_lion_swebench_verified`——都经过此函数)。
- raise 后果:`verified_runner._run_post_processing` 的现有
  `except Exception` 已捕获 → `_analysis_failure(...)` →
  `DeepEvalAnalysisStatus.FAILED` + reason 含
  "CONFIDENT_API_KEY must not be set" 归因,`task_result` 不变
  (符合 spec §9"分析失败只落 deepeval 字段")。

### 2.2 "不上报"状态记录

- 成功路径:`analyze_verified_report` 返回前
  `model_copy(update={"deepeval": analysis.model_copy(update={
     "extensions": {**analysis.extensions, "telemetry": "off"}}})`——
  复用 `DeepEvalAnalysis.extensions`(models.py:659),不新增模型字段。
- 报告 JSON/看板自动携带(`verified-report.json`),运行日志不额外打点。

### 2.3 误导横幅的处置(不 monkeypatch)

- "Posting the run anyway ... Confident AI dashboard":
  `test_run.py:1128`,条件 `valid_scores == 0`;P1-1/P1-2 修复后
  指标有分,真实闭环不再打印。验收依赖真实重跑。
- "Run 'deepeval view' ... Confident AI":`test_run.py:1183`,
  非 confident 分支固定文案,无官方开关 → 在
  `docs/agent-e2e-verified-run.md` 的评测说明中注明为已知 SDK 输出。
- 本 PR 不 monkeypatch / 不重定向 stdout(易碎,违背最小实现)。

## 3. P1-1 工具名 + 时间戳(design)

### 3.1 工具名(camelCase 映射)

`trace.py`:
- `record()`:`_find_text(safe_payload, "tool_name", "name", "toolName")`
  —— 加 camelCase 键,顺序不敏感(同一事件只会命中其一)。
- `_event_summary` 的 selected keys 补 `"toolName"`:`("tool_name",
  "name", "toolName", "reason", "stop_reason")`,使摘要携带工具名
  (judge reason 引用工具名的验收点)。
- 循环候选检测依赖 `tool_name` 非空,自动恢复(无需改动)。

### 3.2 时间戳

`TraceEvent`(trace.py:39)新增两个可选字段(与 `DeepEvalTrajectoryEvent`
对齐,`deepeval_analysis.py:536-537` 的 `getattr` 投影零改动贯通):

```python
started_at: datetime | None = None
finished_at: datetime | None = None
```

`record()` 提取规则:
1. payload 中 `message` 映射(marker: `Message*`/`Turn*` 事件)取
   `message.timestamp`(int,Unix 毫秒)→ `utc_from_ms()` →
   `started_at == finished_at`(事件级精度,无更细粒度);
2. 无 message(如 `ToolExecutionStart/EndEvent`):
   `started_at == finished_at == utc_now()`(记录器接收时刻,
   即事件刚发生的时刻);
3. 两字段恒同时非空或同时 None(工具:内部 `_event_timestamps(payload)`
   返回二元组)。

`utc_now()` 已有(`models.py:115`),`trace.py` 从 `.models` 补充导入;
`datetime.fromtimestamp(ms / 1000, tz=timezone.utc)` 本地辅助
`_utc_from_ms`。

`record_tool_call()`(合成路径)同样填 `utc_now()`。

影响面(已核):
- `TraceSummary.trace_digest` 变化(时间戳进 digest)——预期行为,
  无跨版本可比性承诺。
- `write_json` 的 `schema_version="agent-e2e/v1"` 不 bump:字段可选,
  worker 写入与 runner 读取(verified_runner.py:660 字面量校验)同 PR
  演进,旧 trace 文件可被新代码读(`default=None`)。
- `DeepEvalTrajectoryEvent` / Opik span 已消费这些字段,贯通零改动。

## 4. P1-2 噪声过滤(design)

`build_deepeval_trajectory`(deepeval_analysis.py:512)投影前过滤:

```python
NOISE_EVENT_TYPES = frozenset({"message_update"})
visible = [e for e in trace_events if e.event_type not in NOISE_EVENT_TYPES]
projected = visible[:max_events]
```

- 排除列表而非白名单:未来新增事件类型默认保留(向前兼容);
- 只作用于投影,`TraceEvent` 原始持久化、loop 检测、`trace.py` 不变;
- 样本预期:256 → 61(195 个 message_update),上限常量不变;
- 边界:`max_events` 校验逻辑保持,过滤在截断前(先滤后截,
  保证工具/边界信号优先进入)。

## 5. 测试设计

- `tests/benchmarks/test_trace.py`:
  - camelCase `toolName` → `TraceEvent.tool_name` 映射;
  - 事件 `message.timestamp`(ms)→ `started_at/finished_at` UTC
    datetime;无 message 事件 → 接收时刻非 None;
  - 过滤红线不回归:secret/path 脱敏既有断言保持。
- `tests/benchmarks/test_eval_analysis_observability.py`:
  - `CONFIDENT_API_KEY` 已设置(monkeypatch env)→
    `analyze_verified_report` 返回 FAILED 分析(reason 含 key 拒因),
    `task_result` 不变;
  - 未设置 → 分析 COMPLETED 且 `extensions["telemetry"] == "off"`;
  - `build_deepeval_trajectory`:`message_update` 被滤、事件数下降、
    工具事件与时间戳保留。
- 既有断言兼容性:`test_eval_analysis_observability.py` 现有用
  `DeepEvalTrajectoryEvent(started_at=..., finished_at=...)` 构造,
  无冲突;`test_trace.py` 现有事件构造无 message/timestamp → 默认
  None,digest 断言若存在需随新字段同步(实施时逐一核对)。

## 6. 不变量与红线复核

- 脱敏:新字段仅工具名(已有字段的别名键)与时间戳,无正文;
  `extra="forbid"` 保持。
- verdict 不变:分析失败/成功都不触碰 `task_result`
  (spec §9 契约)。
- 不新增依赖、不 monkeypatch、不 bump schema、不改 CLI/退出码。