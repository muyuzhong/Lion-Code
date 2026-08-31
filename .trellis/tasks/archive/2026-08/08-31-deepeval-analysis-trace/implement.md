# Implementation Plan: DeepEval 安全语义工具轨迹

## Preconditions

- 只有用户批准这版最终规划后，才运行 `task.py start` 并进入实现。
- 实现前加载 `trellis-before-dev` 与任务 manifests；保留无关 dirty worktree 内容，只修改任务直接需要的路径。

## Ordered Checklist

1. **先固定安全与兼容契约**
   - 增加失败测试，证明安全相对路径、pytest 目标和错误类型可见。
   - 增加负例，证明绝对/Verifier 路径、原始 command、stdout/stderr、源码正文、reasoning 和 secret 不会序列化。
   - 保持现有 `harbor-trace.json` 与 `ProcessEvidence` 断言不变。

2. **实现单一 Analysis Trace 投影**
   - 在新 `analysis_trace.py` 中实现 `AnalysisTraceEvent`、`AnalysisTrace`、投影和加载校验。
   - 按原始 `sequence` 输出 tool call/result，用 `tool_call_id` 关联，不创建 decision window。
   - 只为当前真实 built-in 工具增加必要的安全投影；未知项降级为 `other`。

3. **写出并运输附加文件**
   - worker 在现有 trace 旁写出 `analysis-trace.json`。
   - Harbor 用现有受控文件路径规则将其复制到 host。
   - 不改 patch export、官方 Harness 输入或现有 trace 内容。

4. **让 DeepEval 消费语义轨迹**
   - DeepEval adapter 只接受校验后的 Analysis Trace；缺失或非法时沿用 typed unavailable/partial。
   - 为 `ArgumentCorrectnessMetric` 构造带安全参数的 `ToolCall`。
   - 用窄化 `ToolDecisionQuality` GEval 替换旧的 broad trajectory 评价，并要求 reason 引用 `[seq=N]`。
   - 复用现有 `DeepEvalMetricResult`、模型元数据、超时和错误处理；不新增 finding/diagnosis 模型。

5. **最小报告接线**
   - 复用现有 DeepEval metric 列表渲染，两项分别展示 status、score、reason。
   - 官方结果始终先展示，且不受 DeepEval 状态影响。
   - 不接 ProcessVerifier 联合归因，不生成主诊断，不改 Opik。

6. **Targeted validation**
   - 运行 Analysis Trace、DeepEval adapter、Verified 运输/组合和 report 的受影响测试。
   - 运行聚焦 compile 与 `git diff --check`；不默认运行全量 suite。

7. **方向性校准**
   - 用同一任务上下文比较合理轨迹与人为退化的参数/工具选择轨迹，要求方向一致，不断言绝对分。
   - 在条件可用时重跑三条既有官方通过任务，记录 Analysis Trace digest/truncation、两项指标、Judge 模型/指纹/采样和官方结果。
   - 外部环境或凭证不可用时明确报告 blocked，不用旧 digest 轨迹替代。

8. **收尾**
   - 只更新与新 Analysis Trace 和两个 DeepEval 指标直接相关的评测 spec。
   - 检查任务 diff 不包含 ProcessVerifier 模型迁移、diagnosis synthesis 或 Opik 改造，再进入 Trellis check。

## Targeted Validation Commands

```powershell
python -m pytest tests/benchmarks/test_analysis_trace.py -q
python -m pytest tests/benchmarks/test_eval_analysis_observability.py -q
python -m pytest tests/benchmarks/test_verified_execution_chain.py tests/benchmarks/test_verified_cli_composition.py -q
python -m compileall -q benchmarks/agent_e2e tests/benchmarks
git diff --check
```

实现时若实际测试文件名不同，使用仓库现有的最窄对应测试，不扩大为全量测试。

## Risk and Rollback Points

- **隐私回归：** 隐私负例未通过前停止，不调用在线 Judge。
- **DeepEval 4.2 API 不匹配：** adapter 返回 unavailable，不改 vendor、不静默升级依赖。
- **Judge 方差：** 指标固定为两个，轨迹有界，只做方向性校准。
- **旧运行缺少语义数据：** 明确 unavailable；需要证据时重跑，不尝试逆转 digest。
