# PRD: Controlled Experiment Closure——让受控注入真正进入评测协议

> 来源:PR #144 审查反馈(用户第四轮指示)。判断:过程信号一侧已从
> 「启发式检测」升级为「结构化事实检测」(ProcessEvidence 成立);
> 但受控实验一侧仍有一个关键缺口——**注入能力存在但正式评测没用它**。
> 收口后再进入 Gate V2(真正的决策层)。

## 1. 背景与目标

现状(已勘察核实):

```text
代码支持受控注入          ✓  (variant_injection.py + run_agent_worker 参数)
单元测试证明注入可用      ✓  (test_variant_injection.py)
正式评测真的使用注入      ✗  ← 缺口
```

具体事实:
- `run_agent_worker(..., injection_spec=...)` 有参数,但
  `worker_entrypoint.py` 构造 recorder 后调用 `run_agent_worker(request,
  trace_recorder=recorder)` **不传 injection_spec**;
- Harbor 执行链(`harbor_runner` → `--agent-kwarg manifest_json/task_json`
  → `harbor_agent.py` 写 `/installed-agent/request.json` →
  `worker_entrypoint.main()`)里**没有 injection 的任何传递通道**;
- **隐藏缺陷**:`harbor_agent._SOURCE_FILES` 只上传 5 个文件
  (agent_worker/backend/models/trace/worker_entrypoint),而
  `trace.py` 已 import `evidence`、`agent_worker.py` 已 import
  `variant_injection` → **正式 Harbor 容器 ImportError**;
- `PairedExperimentReport.injection_fingerprint` 目前**永远不会被赋值**
  (build() 里默认 None);
- `ExperimentKind.CONTROLLED` 只看 `agent_code_sha` 相等,不校验
  「treatment 真的发生了」→ 可能出现在两侧都走默认 prompt 的情况下
  报告却写「机制导致」;
- compression 无真实开关,但 CONTROLLED 仍允许
  `compression_version v1→v2` 且报告声称归因 → 语义漏洞。

目标:把因果实验链真正闭合(不再扩架构),让「CONTROLLED」成为
**经过验证的 treatment 事实**,而不是声明。

## 2. 需求

### 2.1 VariantInjectionSpec 正式进入评测协议

- `ExperimentManifest`(或 manifest.extensions)携带
  `VariantInjectionSpec`(harbor_runner 构造请求时传入,随
  manifest_json 进入容器);
- `harbor_agent._SOURCE_FILES` 补 `evidence.py` 与
  `variant_injection.py`(修复 ImportError);
- `worker_entrypoint.py` 从 manifest 读取 spec → 传给
  `run_agent_worker(..., injection_spec=...)`;
- baseline 与 candidate 各自使用自己的注入配置。

### 2.2 运行结果记录真实 injection 证据

- worker 执行时产出执行证据并落入 WorkerResult 受控字段:

```text
requested_variant          # 声明的 prompt/tool_policy 版本
resolved_variant           # 实际解析结果(命中/未命中)
injection_fingerprint      # 实际注入内容指纹(非空 = 真的注入了)
```

- `TaskResult` / `PairedExperimentReport` 透传两侧注入证据;
  `report.injection_fingerprint` **不再允许默默为 None**(受控时必填)。

### 2.3 CONTROLLED 判定要求「处理真的发生」

```text
CONTROLLED =
  same agent_code_sha          (已有)
+ same environment             (已有 invariants)
+ only declared change         (已有)
+ injection resolved           (两侧 requested 命中映射)
+ actual injection differs     (两侧 fingerprint 不同且非空)
```

不满足则**拒绝标记 CONTROLLED**(报告必须明确降级为 REGRESSION 或
NEW 枚举值如 UNSUPPORTED_TREATMENT,措辞如实)。

### 2.4 compression 禁止作为 Controlled treatment

- `compression_version` 无真实运行开关 → 声明变更含 COMPRESSION 时
  不得产生 CONTROLLED(只能 REGRESSION 或明确标注
  「declared-only,不可归因」);
- 报告措辞与报告模型、spec 同步;未来有压缩注入点再开放。

## 3. 验收准则

- [ ] manifest 携带 VariantInjectionSpec;harbor_runner 构造请求时可传
      且随 manifest_json 进入容器。
- [ ] `harbor_agent._SOURCE_FILES` 含 evidence.py / variant_injection.py
      (ImportError 缺陷修复);容器内 worker 真正收到 spec。
- [ ] worker 结果含 `requested_variant / resolved_variant /
      injection_fingerprint` 证据;TaskResult/Report 透传。
- [ ] CONTROLLED 判定:injection 未解析 / fingerprint 缺失 /
      两侧 fingerprint 相同 → 不产生 CONTROLLED;同 code 但无真实
      treatment 时报告明确降级并如实措辞。
- [ ] declared_changes 含 COMPRESSION 时永不产生 CONTROLLED
      (compression 归入 regression 或 declared-only)。
- [ ] `report.injection_fingerprint` 受控时必填(模型校验),不再静默
      None。
- [ ] 单元测试覆盖:注入解析命中/未命中、fingerprint 不同/相同、
      compression 禁入受控、报告降级措辞、Harbor source 清单断言。
- [ ] tests/benchmarks 全绿(环境性失败除外);ruff check + format
      基线通过。

## 4. 非目标

- 不建立 compression 真实运行开关(仍为声明字段)。
- 不做 Gate V2 / comparison.py / McNemar(收口后自然进入)。
- 不新增大型模块;只打通与收紧现有链路。
- 不改 ProcessEvidence / ProcessVerifier(已成立)。

## 5. 风险与开放问题

- manifest 增字段会触碰 `ExperimentManifest`(frozen 快照)与既有
  fixture;优先放 `manifest.extensions` 避免 schema 漂移,若严谨
  校验需要(如 fingerprint 纳入)再评估显式字段(实施时定)。
- Harbor 容器 import 修复需要确认 `_SOURCE_FILES` 是否还有其它
  隐式依赖(如 pydantic 依赖 wheel,仅源码文件需列全)。