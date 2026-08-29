# Design: 过程验证器(ProcessVerifier 确定性轨迹规则)

> 配套 `prd.md`。本文件记录边界、数据流、规则细节与取舍;实施时以
> `implement.md` 的顺序清单执行。

## 1. 涉及面与边界

| 文件 | 动作 |
|---|---|
| `benchmarks/agent_e2e/process_verifier.py` | **新增**:`ProcessVerificationStatus` / `ProcessViolationType` / `ProcessViolation` / `ProcessVerification` / `ProcessVerifier` / `verify_trace` |
| `benchmarks/agent_e2e/models.py` | **只读复用** `TaskSpec`(public_validation_commands) / `TaskResult` / `AgentRunSummary` |
| `benchmarks/agent_e2e/trace.py` | **只读复用** `TraceEvent`;不修改脱敏逻辑 |
| `benchmarks/agent_e2e/regression.py` | **不调用,不导入其私有函数**;仅参考其 marker 匹配思路(独立实现,避免私有依赖) |
| `benchmarks/agent_e2e/harness_runner.py` / `worker_entrypoint.py` | **不修改**(离线消费已落盘轨迹) |
| `tests/benchmarks/test_process_verifier.py` | **新增** 单元测试 |

## 2. 数据流

```
TaskSpec(含 public_validation_commands) ─┐
TraceEvent 序列(harbor-trace.json)      ─┼→ ProcessVerifier.verify(...)
TaskResult(verdict / agent_run)          ─┘        │
                                           确定性规则逐条评估
                                                   ▼
                              ProcessVerification{
                                status: valid|violation|critical_veto,
                                violations: [ProcessViolation, ...] }
```

## 3. 具体设计

### 3.1 模型(全部 VersionedModel,遵循严格契约)

```python
class ProcessVerificationStatus(str, Enum):
    VALID = "valid"
    VIOLATION = "violation"
    CRITICAL_VETO = "critical_veto"

class ProcessViolationType(str, Enum):
    REPEATED_TOOL_CALL = "repeated_tool_call"
    TOOL_ERROR_NOT_RECOVERED = "tool_error_not_recovered"
    VALIDATION_MISSING = "validation_missing"
    TEST_TAMPERING = "test_tampering"
    PREMATURE_TERMINATION = "premature_termination"
    CONTEXT_REGRESSION = "context_regression"

class ProcessViolation(VersionedModel):
    violation_type: ProcessViolationType
    severity: ProcessSeverity            # violation | critical_veto
    evidence_offsets: tuple[int, ...]    # TraceEvent.sequence
    description: str = Field(max_length=320)   # 脱敏中文描述
    extensions: dict[str, Any] = {}

class ProcessVerification(VersionedModel):
    task_id: str
    attempt: int | None = None
    outcome_verdict: TaskVerdict | None = None   # 只记录引用,不覆盖判定
    status: ProcessVerificationStatus
    violations: tuple[ProcessViolation, ...] = ()
    extensions: dict[str, Any] = {}
```

- 聚合规则:`status = CRITICAL_VETO` 当且仅当存在 severity=critical_veto
  的 violation;否则 `VIOLATION` 当且仅当存在任意 violation;否则 VALID。
- `ProcessVerification` **不改变** `TaskResult.verdict`(分离原则)。

### 3.2 `ProcessVerifier` 配置(确定性)

```python
class ProcessVerifier:
    def __init__(
        self,
        *,
        repeat_threshold: int = 3,          # repeated_tool_call 连续 N 次
        error_repeat_threshold: int = 2,    # tool_error_not_recovered 重复次数
        protected_markers: Sequence[str] = ("test", "skip", "pytest",
                                            "verifier", "gold",
                                            "validation_command"),
        compaction_markers: Sequence[str] = ("context", "compact",
                                             "compaction"),
        error_markers: Sequence[str] = ("tool_error", "toolerror",
                                        "permission_denied", "denied",
                                        "unauthorized", "error"),
        premature_markers: Sequence[str] = ("max_turn", "turn_limit",
                                            "max_cost", "budget", "abort",
                                            "cancel", "timeout"),
    ) -> None: ...

    def verify(self, *, task: TaskSpec, task_result: TaskResult,
               trace_events: Sequence[TraceEvent]) -> ProcessVerification
```

### 3.3 规则实现细节

统一预处理:`events = tuple(sorted(trace_events, key=lambda e: e.sequence))`,
校验 sequence 唯一(与 `classify_failure._validate_trace_sequences` 同思路,
独立实现)。

1. **repeated_tool_call**(violation):
   - 滑窗:连续 `repeat_threshold` 个事件的 tool_name 相同且
     argument_digest 相同(argument_digest 为 None 时不触发)。
   - evidence_offsets = 窗口内全部 sequence。
2. **tool_error_not_recovered**(violation):
   - 找到 error marker 事件(event_type 含 error_markers 之一),随后
     `error_repeat_threshold` 次工具调用与错误前的最近一次调用
     fingerprint(同 regression `_tool_call_fingerprint` 思路:
     tool_name + argument_digest + workspace_fingerprint)相同 →
     未改变策略持续重复。
   - evidence_offsets = 错误事件 + 后续重复调用事件。
3. **validation_missing**(critical_veto):
   - 前置条件:`task.public_validation_commands` 非空,且
     `task_result.verdict == TaskVerdict.PASSED`(只有声称完成才需要
     验证;FAILED 不含"声称完成"语义,防误报)。
   - 判定:轨迹中不存在任何与验证命令对应的可观测信号。信号匹配:
     对每条 validation command 提取命令首词(如 `pytest` / `npm` /
     `python -m pytest`),若任一命令首词出现在任一 TraceEvent 的
     event_type / summary / tool_name 中,视为存在验证行为。
   - 全部命令都无信号 → critical_veto。该命令提取在构造时完成一次,
     可审计(放进 extensions 记录命令首词列表)。
4. **test_tampering**(critical_veto):
   - 命中模式:事件 tool_name 为写类工具(如 edit / write / patch,
     名单可配 `write_tool_markers`),且 event_type / summary /
     tool_name 含 protected_markers 之一(如 pytest / test / skip /
     verifier),视为触碰受保护区域。
   - 目的:捕获"改测试 / skip 验证"式破坏;V1 命中即记录为
     critical_veto,但**不自动否决** outcome(见 PRD 2.3)。
5. **premature_termination**(violation):
   - `task_result.agent_run.stop_reason` 或轨迹事件含 premature_markers
     之一 → 触发。(与现有 `_is_premature_stop` 同语义,独立实现。)
6. **context_regression**(violation):
   - 找 compaction 事件(event_type 含 compaction_markers)之后
     **首个工具调用**;若该调用与 compaction 前最近的失败/错误调用
     fingerprint 相同 → 压缩后丢失"此路不通"的关键约束,触发。
   - evidence_offsets = compaction 事件 + 首调用 + 压缩前失败调用。

### 3.4 伪命中控制与可审计性

- 所有 marker 名单为构造参数(默认值如上),测试可注入;
- `verify()` 纯函数式、无随机、无 I/O;同一输入必得同一输出;
- 每条 violation 的 description 只含受控字段摘要与触发条件,不含
  原始 payload(沿用 trace.py 脱敏边界);
- `verify_file() -> ProcessVerification`:读取 `harbor-trace.json`
  格式(顶层 `events` 列表),反序列化 `TraceEvent` 后调 `verify()`。

### 3.5 与 classify_failure 的关系(用户已确认并存)

- 两者规则语义部分重叠(loop≈repeated_tool_call 等),但**互不调用、
  互不依赖**:classify_failure 保留现状服务失败回流;ProcessVerifier
  独立服务"全轨迹过程判定"。
- 未来若统一(诸如 FailureRecord 从 ProcessViolation 投影),另立任务,
  本轮不做。

## 4. 取舍与理由

- **离线运行而非 worker 内联**:host 侧已有 `harbor-trace.json`,
  规则不需要容器内上下文;零执行链改动,符合"只重构判定层"。
- **validation_missing 只在 PASSED 判定**:FAILED 无"声称完成"语义,
  避免把能力不足误判为过程造假;命令首词匹配是保守近似,优先防误报。
- **test_tampering V1 标记为 critical 但不 veto 现有判定**:判定分离
  是铁律;V2 gate 才决定 veto 语义。
- **不导入 regression.py 私有函数**:独立实现 marker 匹配(约等同
  现有 30 行),避免跨模块私有耦合。
- **status 聚合规则简单确定**:critical_veto 优先于 violation 优先于
  valid,任何人都能手工复核。

## 5. 验证命令

- 单元测试:`python -m pytest tests/benchmarks/test_process_verifier.py -q`
- 回归:`python -m pytest tests/benchmarks -q`