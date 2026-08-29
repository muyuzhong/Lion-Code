# Design: 过程证据投影(TraceEvent → ProcessEvidence)

> 配套 `prd.md`。记录边界、数据流、具体改造与取舍。

## 1. 涉及面与边界

| 文件 | 动作 |
|---|---|
| `benchmarks/agent_e2e/evidence.py` | **新增**:`ProcessEvidence` / `ToolPhase` / `TargetScope` / `CompactionState` / `TerminationKind` / `ProcessEvidenceProjector` |
| `benchmarks/agent_e2e/trace.py` | 修改:`TraceRecorder` 持有 projector,`record()` 同步投影,`write_json` 输出 `evidence` 数组;**不动 TraceEvent schema** |
| `benchmarks/agent_e2e/worker_entrypoint.py` | 修改:`TraceRecorder()` 构造时传入任务验证命令与投影配置 |
| `benchmarks/agent_e2e/harbor_runner.py` | 只读复用(evidence 随 trace.json 一起落盘,无需改动) |
| `lion_code/core/events.py` | **只读**类型来源(import 构造 typed event 做测试即可) |
| `tests/benchmarks/test_process_evidence.py` | **新增**;`tests/benchmarks/test_trace.py` 可能小改(write_json 结构) |

## 2. 数据流

```
typed Core Event(record())
        │
        ├──► 既有 TraceEvent 记录(零改动)
        │
        └──► ProcessEvidenceProjector.project(event)
                 │ 脱敏前提取:
                 │   tool_call_id / tool_phase / tool名+参数digest
                 │   is_error / 路径→target_scope / 命令→validation
                 │   compaction / termination
                 ▼
             ProcessEvidence(sequence 关联)
        │
        ▼
write_json → { events: [...], evidence: [...], loop_candidates: [...] }
```

## 3. 具体设计

### 3.1 模型(`evidence.py`,全部 VersionedModel)

```python
class ToolPhase(str, Enum):       # start | update | end
class TargetScope(str, Enum):     # source | test | verifier | other
class CompactionState(str, Enum): # started | completed
class TerminationKind(str, Enum): # turn_failed | cancelled

class ProcessEvidence(VersionedModel):
    sequence: int                       # 与被投影 TraceEvent 的 sequence 相同
    tool_call_id: str | None = None     # 聚合 start/update/end
    tool_phase: ToolPhase | None = None
    tool_name: str | None = None
    tool_fingerprint: str | None = None # digest(工具名 + 参数)
    is_error: bool | None = None        # 仅 end 事件有意义
    target_scope: TargetScope = TargetScope.OTHER
    path_digest: str | None = None      # 已分类路径的哈希(无原文)
    validation_command: bool = False
    validation_command_id: str | None = None   # "validation-0"
    command_digest: str | None = None          # 命令正文哈希(无原文)
    compaction: CompactionState | None = None
    termination: TerminationKind | None = None
    extensions: dict[str, Any] = {}
```

### 3.2 投影器

```python
class ProcessEvidenceProjector:
    def __init__(
        self,
        *,
        validation_commands: tuple[str, ...] = (),
        path_scope_rules: PathScopeRules | None = None,  # 见 3.3
        write_tool_names: frozenset[str] = frozenset(
            {"edit_file", "write_file", "patch", "apply_patch", "bash"}),  # 待定，见风险
    ) -> None:
        self._command_heads = ...  # 预计算命令首词(复用 _command_heads 思想)

    def project(self, event: object) -> ProcessEvidence | None:
        """对可识别 typed event 返回证据;未知事件返回 None(不抛错)。"""
```

- 识别依据:事件对象的 `type` 字段(`tool_execution_start` 等,
  与 `lion_code/core/events.py` 的 Literal 一致)。
- `tool_fingerprint`:复用 `loop_fingerprint(tool_name, argument_digest,
  workspace)` 思路(项目已有稳定指纹函数,不新造)。
- 验证命令匹配:检查事件 args/command 字段中的命令文本,规范化
  (去空格/首词)后与任务卡 `public_validation_commands` 匹配;
  命中 → `validation_command=True` + `validation_command_id="validation-N"`
  (N 为命令索引)+ command_digest(SHA-256)。
- 命令文本从 `args["command"]` 或 `args["content"]` 等受控字段提取,
  只用于「比对 + 哈希」,不落盘。
- `is_error` 仅 `tool_execution_end` 事件有值(真实字段)。

### 3.3 路径分类规则 `PathScopeRules`

输入:args 中的路径字段(cwd / file / path / workspace,与
`sanitize_payload` 的 `_PATH_KEYS` 一致)。

```python
@dataclass(frozen=True, slots=True)
class PathScopeRules:
    test_prefixes: tuple[str, ...] = ("tests/", "test/")
    verifier_prefixes: tuple[str, ...] = (".harbor/", "hidden/",
                                          "verifier/", "gold/")
    source_prefixes: tuple[str, ...] = ()   # 其余落入 source 需显式
```

判定优先序:verifier → test → source → other。任何路径都产出
`path_digest`(哈希),**原文绝不落盘**。分类规则可审计、可测试。

### 3.4 TraceRecorder 集成

```python
class TraceRecorder:
    def __init__(self, *, trace_id=None, max_preview=240,
                 projector: ProcessEvidenceProjector | None = None):
        self._projector = projector or ProcessEvidenceProjector()
        self._evidence: list[ProcessEvidence] = []

    def record(self, event: object) -> None:
        ...  # 既有逻辑不变
        evidence = self._projector.project(event)
        if evidence is not None:
            self._evidence.append(evidence)

    def write_json(self, path) -> None:
        payload = {..., "evidence": [e.model_dump(mode="json")
                                     for e in self._evidence]}
```

- `worker_entrypoint.py`:构造 recorder 时传
  `ProcessEvidenceProjector(validation_commands=task.public_validation_commands)`。
- `record_tool_call()`(合成路径,离线测试用)同步产出合成证据
  (tool_phase=end)。

### 3.5 取舍

- **独立数组而非扩展 TraceEvent**:严格 schema + 既有脱敏测试零
  改动;旧文件向后兼容(evidence 缺失 = 空数组,reader 容错)。
- **投影发生在 record() 内**:worker 只有一个订阅点
  (`agent.subscribe(recorder.record)`),投影与记录同源同序,
  保 sequence 对齐。
- **validation_commands 提前注入**:投影器构造时拿到任务卡命令,
  避免在投影时依赖上下文。
- 隐私不变式由测试强制断言(序列化 JSON 中不含命令/路径/输出)。

## 4. 验证命令

- `python -m pytest tests/benchmarks/test_process_evidence.py -q`
- `python -m pytest tests/benchmarks/test_trace.py tests/benchmarks/test_agent_worker.py -q`
- `python -m pytest tests/benchmarks -q`

## 5. 风险

- 路径字段的实际取值形态需与真实工具参数核对(edit bash 等工具
  的 args 结构);先按 `_PATH_KEYS` 约定实现,校准阶段(子任务三)
  用真实 trace 复核分类。
- write_tool_names 名单需与真实工具命名对齐(temp 扫描),校准阶段
  修正默认值。