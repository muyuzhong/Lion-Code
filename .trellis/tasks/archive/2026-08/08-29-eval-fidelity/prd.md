# PRD: Evaluation Fidelity——过程证据投影与受控实验语义

> 来源:PR #143 审查反馈(用户直接指示)。核心判断:PR #143 建立了
> PairedExperiment 与 ProcessVerifier 骨架,方向正确,但存在两个
> 底层问题,若不先解决,后续统计检验与 Gate 越严密,越可能是在
> 精确地计算错误信号:
>
> 1. **ProcessVerifier 的规则定义对,但真实 Trace 没有提供足够信息**
>    (tool_call_id / is_error / compaction 未持久化,路径被哈希,
>    描述文本不含命令;真实 trace 实测:tool_execution_end 无 is_error,
>    summary 仅 toolName,validation_missing/test_tampering/repeated_tool_call
>    在真实数据上失效或误判)。
> 2. **HarnessVariant 只是版本声明,不是实验处理变量**(worker 未将
>    prompt_version/compression_version/tool_policy_version 注入
>    Harness;Full Composition 有 custom_system_prompt 等注入点但未用;
>    compression 无注入点)→ 现有配对只能证明「B 版本比 A 好」,
>    不能证明「compression v2 导致了提升」。
>
> 顺序调整:下一 PR 不做 comparison.py + Gate V2(顺延),先做本任务
> 「评估保真度收口」,证明两件事:**声明的 Harness 变量真的只改变了
> 这个变量**;**ProcessVerifier 看到的过程信号真的对应实际行为**。

## 1. 背景与目标

目标:建立一层「语义化过程证据」(Process Evidence),让 ProcessVerifier
读取**明确事实**而非猜测脱敏文本;同时给 PairedExperiment 区分
**受控实验**与**跨版本回归**两种语义,让因果评估真正成立。

隐私原则不变:**不保存完整命令、文件路径、工具输出**。只在脱敏前
做一次语义分类,最终落盘分类结果 + digest。

## 2. 任务地图

| 子任务 | 交付物 | 依赖 |
|---|---|---|
| `08-29-process-evidence-projection` | TraceEvent → ProcessEvidence 语义化投影(tool_call_id / tool_phase / tool_fingerprint / is_error / target_scope / validation_command / compaction / termination) | 无 |
| `08-29-process-verifier-rewrite` | ProcessVerifier 六条规则重写为消费 ProcessEvidence,保持确定性、分离 outcome | evidence-projection |
| `08-29-fidelity-calibration` | 真实 Harbor trace 校准:已知违规能检出、正常 PASS 不误杀;校准基线与报告 | verifier-rewrite |
| `08-29-controlled-vs-regression` | PairedExperiment 区分 Controlled Experiment(同 agent_code_sha)与 Regression Comparison(跨 code_sha);worker 接通已有注入点 | 无(与投影并行) |

## 3. 需求

### 3.1 过程证据投影(子任务一)

- 新增语义化投影层:Core Typed Event → ProcessEvidence,在脱敏**之前**
  提取:
  - `tool_call_id`(真实事件已有,用于聚合 start/update/end 生命周期)
  - `tool_phase`(start / update / end)
  - `tool_fingerprint`(稳定工具指纹)
  - `is_error`(ToolExecutionEndEvent 真实字段)
  - `target_scope` = source / test / verifier(文件路径在哈希前分类,
    如 `lion_code/meta_agent.py → source`、`tests/test_agent.py → test`、
    `hidden/... → verifier`)
  - `validation_command` = true / false(执行命令在脱敏前与任务声明
    的 validation command 对比,落盘 `validation_command_id=validation-0`
    + command_digest)
  - `compaction`(compaction_started / completed)
  - `termination`(turn_failed / cancelled / 预算轮数终止)
- 落盘形态:**独立 ProcessEvidence 数组,不改 TraceEvent schema**
  (用户已确认;现有 TraceEvent 契约、digest、脱敏测试零改动)。
- 隐私边界:只保存分类结果 + digest,不保存命令正文、路径原文、输出。

### 3.2 ProcessVerifier 重写(子任务二)

- 六条规则改为消费 ProcessEvidence:
  - `repeated_tool_call`:按 tool_call_id 聚合生命周期,**一次调用的
    start/update/end 不算多次重复**;仅不同 call 的同指纹调用连续 ≥N
  - `tool_error_not_recovered`:基于 is_error=true 的 end 事件(不再
    猜文本 error marker)
  - `validation_missing`:基于 validation_command 证据(不再在
    summary 里搜 pytest)
  - `test_tampering`:基于 target_scope=test/verifier + 写类工具
    (不再猜哈希路径)
  - `premature_termination`:基于 termination 证据
  - `context_regression`:基于 compaction 证据 + 前后 tool 指纹对比
- 保持:纯确定性、分离 outcome、ProcessVerification 聚合规则不变;
  `verify_file` 升级为可读取 evidence 数组(旧 trace 无 evidence →
  降级策略见 3.3)。

### 3.3 真实校准(子任务三)

- 用真实 Harbor trace(smoke-batch 13 条已存在)做校准:
  - 已知违规能检出:构造/识别真实违规轨迹,规则必须命中
  - 正常 PASS 不误杀:正常轨迹不得产生 critical_veto
- 旧 trace(无 evidence 数组)兼容:读旧文件不崩溃,evidence 缺失时
  输出明确降级标记(如 `evidence_unavailable`),不误判为 valid。
- 校准结论写入报告/文档,作为 ProcessVerifier 的信任基线。

### 3.4 受控实验语义(子任务四)

- `PairedExperiment` 明确区分两种语义:
  - **Controlled Experiment**:同一 `agent_code_sha`,只通过
    HarnessVariant 开关某一能力 → 可以谈「该机制导致了什么变化」
  - **Regression Comparison**:baseline code_sha != candidate code_sha
    → 只能谈「这个版本整体是否回归」
- worker 接通已有的注入点:`custom_system_prompt`(prompt 变量)、
  `tool_registry`(tool_policy 变量);compression 无注入点 → 标注为
  「声明字段,无真实运行开关」写进 spec,真实开关留待后续
  (用户已确认此范围)。
- PairedExperimentReport 记录 experiment_kind,报告区分两种语义的
  结论措辞。

## 4. 验收准则(全局)

- [ ] ProcessEvidence 投影:单元测试覆盖各事件类型与隐私边界
      (路径/命令/输出不落盘)。
- [ ] ProcessVerifier 六条规则基于证据重写,同一输入必得同一输出;
      单测覆盖正常/违规/边界;旧契约(无 evidence)不崩溃。
- [ ] 校准:真实 trace 集上已知违规检出、正常不误杀,结论可复核。
- [ ] PairedExperiment:controlled 与 regression 两种语义正确区分,
      报告记录 experiment_kind;worker 注入点接通并有测试。
- [ ] 现有 tests/benchmarks 全绿(项目惯例:仅环境性问题可豁免)。

## 5. 非目标(No-go)

- **不做** comparison.py / McNemar / bootstrap / Gate V2(顺延)。
- **不做** 首错归因 / trajectory-prefix / Harness Regression Corpus(顺延)。
- **不修改** `classify_failure()` 与失败回流链路。
- **不建立** compression 的真实运行开关(仅为声明字段,写 spec 记录)。
- **不保存** 命令正文、文件路径、工具输出等原始信息。

## 6. 风险与开放问题

- 真实 trace 中 `is_error` 未持久化是历史事实,校准需以「新投影 +
  已知违规构造用例」为主,历史 trace 只能验证降级兼容。
- process_evidence_projection 落在 worker 内(容器内),需确认
  Core event 订阅点能拿到 typed event 全量字段(ToolExecutionStart
  等已在 `lion_code/core/events.py` 确认存在)。
- target_scope 分类规则需显式定义路径前缀白名单(source/test/verifier
  的判定),防止误分类导致误杀。