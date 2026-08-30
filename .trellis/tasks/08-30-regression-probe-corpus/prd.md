# PRD: Harness Regression Probe——最小失败片段与确定性回归语料

> 主 PR:把 #149 的 FirstErrorAttribution 转成「最小、确定、可离线重放」的
> Harness 回归样本。来源:用户第七轮规划(08-30),父链路
> `PairedExperiment → Gate V2 → FirstErrorAttribution → Regression Probe
> → Harness Regression Corpus → offline runner`。

## 1. 背景与目标

Gate V2 发现退化,FirstErrorAttribution 定位「从哪一步开始错」,但当前只
输出红acted 可读摘要行。本 PR 把 attribution 背后的结构化
`ProcessEvidence` 裁成**最短充分片段**,沉淀为确定性的 `RegressionCase`
回归语料,并用一个极小的离线 runner 逐条重放,让「以后每次 Harness 改动
先跑回归语料再跑正式 paired evaluation」成为可能。

核心原则:
- **不重新跑模型、不复现整个 Agent 行为**;V1 只做 deterministic slicing;
- **corpus 保存结构化 `ProcessEvidence`**,绝不保存 #149 的可读字符串
  snippet(字符串只给人看,不能作为稳定机器回放协议);
- **只接受高置信、有确定性 violation 的 attribution 自动沉淀**,低置信
  与 PASS→PASS harmless divergence 一律拒绝;
- 不同 violation 的「最小化条件」不同,minimization 必须通过
  `probe_holds` 抽象做 violation-aware 判定,不能只按事件数裁剪。

## 2. 需求

### 2.1 `regression_probe.py`(新模块)——失败片段最小化

- `probe_holds(violation_type, evidence_slice, task, task_result) -> bool`:
  V1 内部直接复用 `ProcessVerifier.verify(...)`,判断目标 violation 在
  给定 evidence 切片上是否仍存在;空 evidence 恒为 False(空 → 降级
  `EVIDENCE_UNAVAILABLE`,不算 violation)。
- `minimize_failure_evidence(...) -> tuple[ProcessEvidence, ...]`:
  greedy 逐事件裁剪(每删一个事件重跑 probe_holds,仍成立就删并重来),
  直到任何单事件都无法删除 → 最短充分片段。初始切片不成立时显式报错
  (调用方误用)。
- 同一算法对 6 类支持 violation 通用;差异全部由 probe_holds 承载
  (`TOOL_ERROR_NOT_RECOVERED` 保留 failed call + 同指纹 repeat;
  `CONTEXT_REGRESSION` 保留 failed call + compaction + compaction 后
  同指纹 call;`TEST_TAMPERING` 只保留 write tool + test/verifier scope)。

### 2.2 `regression_corpus.py`(新模块)——RegressionCase + 离线 runner

- `RegressionCase(VersionedModel)`:case_id / source_task_id /
  source_attempt / source_run_id / first_error_kind / expected_violation /
  expected_status / evidence(最小失败片段)/ source_fingerprint /
  original_evidence_count / minimized_evidence_count。
- 入库判定(`regression_case_from_attribution`):
  - `evidence_available is False` → reject;
  - `confidence < 1.0` → reject;
  - candidate evidence 上无受支持 violation(TEST_TAMPERING /
    TOOL_ERROR_NOT_RECOVERED / VALIDATION_MISSING / CONTEXT_REGRESSION /
    PREMATURE_TERMINATION / REPEATED_TOOL_CALL)→ reject;
  - `TOOL_SELECTION / TOOL_ARGUMENT / UNKNOWN(纯分歧)` 不进入 corpus。
- 离线 runner(`run_regression_corpus`):对每条 case 用 `verify_case` 重放
  evidence,比较实际 violation 与 expected,输出 PASS / FAIL / INVALID,
  聚合为 `RegressionCorpusReport(total/passed/failed/invalid/results)`。

### 2.3 `process_verifier.py`(扩展)——自包含重放

- `ProcessReplayContext(VersionedModel)`:verdict / stop_reason /
  public_validation_commands(verifier 消费的极简上下文)。
- `verify_case(evidence, *, context) -> ProcessVerification`:与 `verify`
  共享同一套规则聚合逻辑,不重建完整 TaskSpec/TaskResult。

## 3. 验收准则(5 条)

1. 长 unrecovered-error 轨迹 → 能裁成更短片段 → 仍触发同一 violation;
2. 删除一个必要事件后 → violation 不再成立 → 说明片段接近最小;
3. confidence < 1.0 → 不允许自动生成 RegressionCase;
4. PASS→PASS harmless divergence → 根本不会进入 corpus;
5. corpus runner 对固定 case → 同输入始终得到同结果(确定性)。

## 4. 非目标

- 不自动修改 Harness、不自动生成代码补丁、无 LLM judge;
- 不做完整 Agent replay、不做 SWE-bench 任务自动生成、不线上自动发布;
- 不做复杂 corpus 管理平台;
- 不改 #149 的 `attribute_first_error` 行为与输出。

## 5. 依赖与开放问题

- 依赖 `08-30-first-error-attribution`(#149)与 `08-29-process-verifier`。
- REPEATED_TOOL_CALL 在 first_error 中映射为 `FirstErrorKind.UNKNOWN`,
  入库判定以「candidate evidence 上实际存在的受支持 violation」为准,
  而不是只按 kind 白名单,避免歧义误拒。
- 文件拆分:按建议两个模块 + 两个测试文件;corpus 薄则不强拆。
