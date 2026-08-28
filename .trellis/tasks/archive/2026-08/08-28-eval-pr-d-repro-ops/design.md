# Design:评测链 PR D(分析可复现与运维)

> 配套 `prd.md`。本文件记录边界、数据流、具体改造与取舍;实施时以
> `implement.md` 的顺序清单执行。

## 1. 涉及面与边界

| 文件 | 动作 |
|---|---|
| `benchmarks/agent_e2e/models.py` | `DeepEvalMetricResult` +samples/score_min/score_max;`DeepEvalMetricFixture` 对应可选字段 |
| `benchmarks/agent_e2e/deepeval_analysis.py` | `analyze_deepeval_case` +judge_samples 采样循环与聚合;parse 透传新字段 |
| `benchmarks/agent_e2e/verified_runner.py` | `VerifiedExecutionRequest` +deepeval_samples/digest_ledger_path;ledger 勾挂 |
| `benchmarks/agent_e2e/digest_ledger.py` | 新增(寻迹数据库模块) |
| `benchmarks/agent_e2e/cli.py` | verified 命令 +`--deepeval-samples`/`--digest-ledger`;新 `digest-lookup` 命令 |
| `benchmarks/agent_e2e/report.py` | 指标行渲染采样次数与范围 |
| `scripts/benchmarks/verified-smoke/cleanup_smoke.sh` | 新增(P2-2 清理脚本) |
| `scripts/benchmarks/verified-smoke/run_smoke.sh` | 传 `--deepeval-samples`/`--digest-ledger` |
| `scripts/benchmarks/verified-smoke/README.md` | 采样、ledger、cleanup 用法 |
| `docs/agent-e2e-verified-run.md` | judge 采样、残留清理、digest 寻迹 |
| `tests/benchmarks/*` | test_eval_analysis_observability.py、test_verified_contracts.py、test_verified_cli_composition.py、test_smoke_cleanup.py(新增)、test_digest_ledger.py(新增)、test_smoke_template_guard.py(静态断言列表) |

不触碰:verdict/退出码语义(verified_run 的)、Harbor/Harness/Opik
阶段、score_gate 语义、SCHEMA_VERSION。

## 2. P1-4 采样设计(deepeval_analysis.py + models.py)

### 2.1 模型字段(DeepEvalMetricResult)

```python
samples: int = Field(default=1, ge=1)
score_min: float | None = Field(default=None, ge=0, le=1)
score_max: float | None = Field(default=None, ge=0, le=1)
```

validator 扩展:
- completed 时:`score_min`/`score_max` 必须同存同缺;`samples > 1`
  时必须齐备,且 `score_min <= score <= score_max`;`samples == 1`
  时允许缺省(均值±范围无意义)。
- 非 completed 时:min/max 必须为 None。
- samples 任意(≥1)。

### 2.2 采样循环(analyze_deepeval_case)

```python
deadline = time.monotonic() + timeout_seconds (若 timeout_seconds)
for metric_name in DEEPEVAL_METRIC_NAMES:
    observations = []
    for _ in range(judge_samples):
        remaining = deadline - time.monotonic() (若 deadline;<=0 → TIMEOUT 观测)
        observations.append(_evaluate_with_timeout(...) 或 _evaluate_direct(...))
    metric_results.append(_metric_result_from_samples(observations, ...))
```

- `_metric_result_from_samples`:
  - `len == 1` → 直接 `_metric_result_from_observation`(语义与 PR C
    完全一致;samples 默认 1)。
  - 每样本先经 `_metric_result_from_observation` 校验(分数有限、
    [0,1]、digest 一致、名称一致)→ 得到 sample_results。
  - completed = 校验通过的样本;全失败 → 返回 `sample_results[0]`
    的 `model_copy(update={"samples": judge_samples})`(沿用失败语义,
    记录总采样次数)。
  - 有成功样本:score = 均值;score_min/max = 成功样本极值;
    reason 取首个成功样本;失败样本数 > 0 时 reason 追加
    `"{n} 次采样失败"`;threshold/threshold_met 用均值按
    `DEEPEVAL_METRIC_THRESHOLDS` 重算(直接构造重新触发 validator)。

### 2.3 透传链

- `analyze_verified_report(..., judge_samples: int = 3)` →
  `analyze_deepeval_case(..., judge_samples)`。
- `VerifiedExecutionRequest.deepeval_samples: int = 3`;
  `_validate_request` 校验 ≥1;`_run_post_processing` 传参。
- CLI `--deepeval-samples`(type=int, default=3)。
- `run_smoke.sh`:`--deepeval-samples "${DEEPEVAL_SAMPLES:-3}"`;
  `smoke.env.example` 加可选注释变量(不要求填写,缺省 3)。

### 2.4 fixture 兼容

`DeepEvalMetricFixture` 增加可选字段 `samples: int = 1`/`score_min`/
`score_max`(additive);`parse_deepeval_analysis` 透传;旧 fixture 无
字段 → 默认值,`DeepEvalMetricResult` validator 放行
(samples==1,min/max None)。采样次数默认 1 时报告仪表无需变化。

### 2.5 渲染(report.py)

completed 指标行:

```
`TaskCompletionMetric`:0.4733;阈值 0.5000;未达阈值;采样 3 次;
范围 0.4000–0.5500;状态 `completed`;原因:...
```

- `samples > 1` 时追加 `;采样 {samples} 次` 与 `;范围 {min:.4f}–{max:.4f}`
  (min/max 齐备时)。
- `samples == 1` 时不追加(旧报告输出样式不变)。

## 3. P2-2 清理脚本(cleanup_smoke.sh)

### 3.1 结构(与 run_smoke.sh 同款路径推导)

```bash
SMOKE_TOOL_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd "$SMOKE_TOOL_DIR/../../.." && pwd)
RESULT_ROOT=${SMOKE_RESULT_ROOT:-$ROOT/benchmarks/agent_e2e/results}
WORK_DIR="$RESULT_ROOT/smoke-flask-5014"
DRY=${SMOKE_CLEAN_DRY_RUN:-0}; IMAGES=${SMOKE_CLEAN_IMAGES:-0}
```

### 3.2 路径守卫与删除

- 解析 `WORK_DIR`(cd + pwd);不通过 `[ -d ]` 时按不存在处理但路径
  仍必须位于 `RESULT_ROOT` 之下(`case "$WORK_DIR" in "$RESULT_ROOT/"*)
  ;; *) exit 2`),拒绝越界(`..`、绝对路径绕过一律 exit 2)。
- 删除项(仅这三项,`run-*` 证据目录永不删除):
  `$WORK_DIR/harbor-home`、`$WORK_DIR/hf-home`、`$WORK_DIR/xdg-cache`
  (`rm -rf`,失败 exit 2;干跑仅打印)。
- `IMAGES=1`:`docker images --format '{{.Repository}}:{{.Tag}}'` 过滤
  `^swebench/sweb.eval` 逐一 `docker image rm`;docker 不可用或删除
  失败 → 打印警告、不中断(本机运维尽力而为),最终仍 exit 0。
- 输出摘要:列出删除/将删除的路径与镜像、目录大小(du -sh 尝试);
  清理后提示"缓存可重建,评测可无损重跑"。

## 4. P2-3 寻迹数据库(digest_ledger.py)

### 4.1 模型

```python
class DigestLedgerEntry(VersionedModel):
    digest: str = Field(min_length=64, max_length=64)
    kind: Literal["input", "trace", "payload", "argument"]
    task_id: str | None = Field(default=None, max_length=160)
    run_id: str | None = Field(default=None, max_length=128)
    event_type: str | None = Field(default=None, max_length=160)
    tool_name: str | None = Field(default=None, max_length=160)
    preview: str | None = Field(default=None, max_length=320)
    first_seen_at: datetime = Field(default_factory=utc_now)
    last_seen_at: datetime = Field(default_factory=utc_now)
    count: int = Field(default=1, ge=1)
```

- preview 写入口统一走 `redact_text`(≤320);`append` 前对 preview
  与全部字符串字段做敏感键检查(`_reject_sensitive_keys` 风格)。

### 4.2 DigestLedger(append-only JSONL)

```python
class DigestLedger:
    def __init__(self, path: Path): ...
    def append(self, entries: Sequence[DigestLedgerEntry]) -> None:
        # 'a' 追加,逐行 canonical_json;首行写 schema 头
        # ({"schema_version": "agent-e2e/v1", "kind": "digest-ledger"})
    def lookup(self, digest: str, *, limit: int = 50) -> tuple[DigestLedgerEntry, ...]:
        # 全文件扫描;按 (digest, kind) 取最近一条(last_seen_at 最大)并
        # 聚合 count;按 last_seen_at 倒序,总条数 ≤ limit
    def count(self) -> int
```

- 无第三方依赖;单次写一行;共享文件多进程追加用 `a` 模式,
  行级原子性够用(本机单用户运维场景)。

### 4.3 勾挂(verified_runner)

- `VerifiedExecutionRequest.digest_ledger_path: Path | None = None`
  (不设 → 不写,既有测试零影响)。
- `_run_post_processing` 在 trajectory/input_digest 确定后、分析前:

```python
if request.digest_ledger_path is not None:
    _write_digest_ledger(request, trajectory, input_digest)
```

- `_write_digest_ledger` 构造条目:
  - input:`input_digest` + preview=redact_text(public_prompt, 160)
  - trace:`trajectory.trace_digest` + preview=f"轨迹 {len(events)} 事件"
  - payload/argument:每个投影事件(`event.payload_digest` 与
    `event.argument_digest`)+ event_type/tool_name/时间。
- 写失败(OSError/ValueError)捕获后仅记 stderr 一行警告,不改变
  主链结果(观测性设施不阻塞评测)。

### 4.4 CLI digest-lookup

```
python -m benchmarks.agent_e2e digest-lookup --ledger <path> <digest...>
```

- 输出 JSON:`{"digest": ..., "found": bool, "entries": [...]}`
  (每 digest 一条;entries 为 lookup 结果,kind 分组聚合后按
  last_seen 倒序)。
- 退出码:0=全部找到;1=存在未找到(输出含 found:false;仍打印
  找到的部分);2=ledger 文件缺失/不可读。

### 4.5 模板传参

`run_smoke.sh` 增加:

```bash
LEDGER_FILE="${SMOKE_LEDGER_FILE:-$RESULT_ROOT/digest-ledger.jsonl}"
... --digest-ledger "$LEDGER_FILE" ...
```

(results/ 整目录 gitignore,文件天然不入库;`SMOKE_LEDGER_FILE` 可覆写
路径供测试/多主机。)

## 5. 文档与模板

- `scripts/benchmarks/verified-smoke/README.md`:env 表补
  `DEEPEVAL_SAMPLES`(可选,默认 3)与 `SMOKE_LEDGER_FILE`;新增
  "残留清理"小节(cleanup_smoke.sh 用法、env、干跑、镜像清理)与
  "digest 寻迹"小节(digest-lookup 用法)。
- `docs/agent-e2e-verified-run.md`:
  - "评分阈值与门禁语义"后补"judge 多次采样"(默认 3 次、均值±
    范围、`--deepeval-samples` 可调);
  - "单题运行"末尾补"运行残留清理"(cleanup_smoke.sh,仅本机运维)
    与"digest 寻迹"(ledger 文件位置、digest-lookup 命令、脱敏约束)。
- `smoke.env.example`:可选分组注释 `DEEPEVAL_SAMPLES`(默认 3)。

## 6. 测试设计

| 文件 | 内容 |
|---|---|
| `test_eval_analysis_observability.py` | 采样聚合:fake judge 交替分数 → mean/min/max/samples=3;部分失败(1 样本抛错)→ reason 含"1 次采样失败"、其余聚合;全失败 → 沿用失败语义且 samples=3;judge_samples=1 → 与 PR C 行为一致;既有 calls 断言改为 3 轮样本顺序 |
| `test_verified_contracts.py` | validator:samples>1 缺 min/max 拒绝;min>max 拒绝;非 completed 带 min/max 拒绝;fixture 显式 samples/min/max 透传 |
| `test_verified_cli_composition.py` | 全链 fake judge 采样 3 轮;`--deepeval-samples 1` 走单样本;md 含"采样 3 次/范围";digest-lookup 经 main() 三态退出码 |
| `test_digest_ledger.py`(新增) | append/lookup/聚合 count/脱敏(写入"私密密钥"后文件与 lookup 均无原文);敏感键拒绝 |
| `test_smoke_cleanup.py`(新增) | 默认删除缓存保留 run-*;干跑不删;越界路径 exit 2;`bash -n` |
| `test_smoke_template_guard.py` | TEMPLATE_FILES 增 cleanup_smoke.sh 与 digest 相关 |

## 7. 取舍记录

- **采样默认 3 次 vs 1 次**:按 backlog 建议默认 3,代价是 judge LLM
  调用 ×3(单题成本约 0.15 → 0.45 USD);可经模板 env 调回 1。
- **不做 seed 化**:SDK LLM 无稳定 seed 语义,假造确定性违背准绳;
  均值±范围是诚实表达。
- **ledger 纯 JSONL 追加**:不引 sqlite(标准库可用但不必要),单机
  行级追加足够;聚合在 lookup 时做,避免写时状态。
- **cleanup 默认不删镜像**:镜像重拉耗时且非"缓存"性质;`IMAGES=1`
  显式显式开启,干跑防误删。
- **ledger 写失败不阻断**:观测性设施降级为警告,评审判定与退出码
  不变量不受影响。
- **不自动清理**:手动运维入口,防误删证据,不入 CI。

## 8. 完成判定(与 prd.md A1–A5 对应)

- A1:采样聚合单测全绿;md 渲染断言;CLI samples 参数贯通。
- A2:cleanup 子进程用例(删除/干跑/守卫/语法)全绿。
- A3:ledger 单测 + runner 注入产物断言 + digest-lookup 三态。
- A4:targeted 全绿 + diff --check + ruff 无新指纹。
- A5:本机模板复跑(报告均值±范围 + ledger 可反查本次 digest);
  cleanup 干跑/实跑验证缓存重建后可复跑;backlog 勾销。