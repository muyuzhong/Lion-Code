# PRD: 真实 trace 校准(Harbor 已知违规检出与正常不误杀)

> 来源:父任务 `08-29-eval-fidelity` 3.3 与用户第 3 点指示:
> 「拿真实 Harbor trace 做一组校准,确认已知违规能检出、正常 PASS
> 不误杀」。
> 前置:子任务一(证据投影)+ 子任务二(规则重写)。

## 1. 背景与目标

规则重写后必须证明「ProcessVerifier 看到的过程信号真的对应 Agent
实际发生的行为」。校准 = 在真实与构造的轨迹上验证:
1. **已知违规能检出**(召回:规则必须命中已知违规);
2. **正常 PASS 不误杀**(精确率:正常轨迹不得产生 critical_veto /
   violation 误报)。

已有素材:`benchmarks/agent_e2e/results/smoke-batch-*` 下 13 条
真实 harbor-trace.json(246 个 tool_execution_end)。注意:这些是
旧格式(无 evidence 数组、无 is_error),因此校准分三层:
- 层 1:构造语义化违规轨迹(typed event → 新投影),验证召回;
- 层 2:构造正常轨迹,验证不误杀;
- 层 3:旧真实 trace 走降级路径,验证「不崩溃 + evidence_unavailable」,
  并统计降级覆盖率。

## 2. 需求

### 2.1 校准集(committed fixtures)

- `tests/benchmarks/fixtures/` 下新增校准夹具目录,含:
  - `violations/`:每类规则 1–2 条已知违规轨迹(typed event + 期望
    违规类型 + severity),如疑改测试(tampering)、跳过验证
    (validation_missing)、错误后重复(error_not_recovered)、压缩后
    重犯(context_regression)等;
  - `clean/`:正常 PASS 轨迹(含验证命令、工具调用多样但合规);
  - `legacy/`:旧格式 trace(无 evidence)。
- 构造方式:直接 import typed event 类(`lion_code.core.events`)
  生成事件序列 → 走 TraceRecorder 投影 → 得到落盘 JSON 作为夹具。

### 2.2 校准执行与报告

- 校准 runner(脚本或 pytest 参数化):对每个夹具运行 `verify_file`,
  断言 expected violations / clean status。
- 输出校准小结(JSON/Markdown):每个夹具的检出结果、违规类型映射,
  以及旧 trace 降级覆盖率(如:246 个 tool 事件中 0 个可语义判定)。
- 校准结论写进任务文档,作为 ProcessVerifier 的信任基线
  (用户明确要求「一组校准」,不是一次性手工检查)。

### 2.3 不误杀客观标准

- clean 夹具:必须 status in {valid, evidence_unavailable 仅对旧文件};
  不得产生 critical_veto。
- violations 夹具:预期违规类型必须出现在 violations 列表中,且
  severity 与夹具声明一致。

## 3. 验收准则

- [ ] fixtures 目录包含 violations / clean / legacy 三类夹具,全部
      可离线运行(不依赖 Harbor / LLM)。
- [ ] 校准 runner 通过:违规夹具全部检出预期违规;clean 夹具零
      critical_veto;legacy 夹具输出 evidence_unavailable 不崩溃。
- [ ] 校准小结可复核(输出文件入库或放入 task 文档)。
- [ ] 旧实测 trace 降级覆盖率统计在文档中(如「13 条旧 trace、
      246 个 tool 事件,evidence 缺失率 100%,语义判定不可用」)。
- [ ] tests/benchmarks 全绿。

## 4. 非目标

- 不重新跑 Harbor 容器生成新格式 trace(无新执行链依赖;
  新格式校准用构造 typed event 足够,执行链契约由单测覆盖)。
- 不调规则阈值来「拟合」校准集(校准是验证,不是调参;如需调参
  须在文档记录理由)。
- 不写 Gate V2 与统计检验。