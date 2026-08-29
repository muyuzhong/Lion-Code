# PRD: 回归探针(TrajectoryPrefixCase / minimize_failure + Harness Regression Corpus)

> 来源:父任务 `08-29-eval-harness-paired-system` PRD 3.5。
> **状态:后续阶段,仅 PRD(依赖 ProcessVerifier 的首错/证据归因,
> 且需前两个子任务落地后验证真实轨迹形态)。**

## 1. 背景与目标

现有失败回流链路「failure → classify → 人工 triage → regression
corpus」有效,但每次保存的是**完整失败任务**(大、慢、且只回答
「整体能不能做成」)。第七章给出更细的定位:**不要找最后一个错误,
而要找到第一个使轨迹偏离正确路径的错误**;把轨迹截到首错之前,
形成最小化的 Harness bad case,专门回答「这个 Harness bug 修好了吗」。

## 2. 需求

### 2.1 `regression_probe.py`(新模块)

- `TrajectoryPrefixCase`:最小回归用例,字段:
  - `source_task_id` / `source_run_id`(溯源)
  - `prefix_events`:轨迹 1..k(首错之前的脱敏事件,复用 TraceEvent)
  - `environment_state`:当前工作区状态摘要(可用受限快照/指纹)
  - `allowed_next_actions` / `forbidden_actions`:可接受下一步动作与
    禁止动作(由首错归因反推)
  - `expected_outcome`:探针的期望行为(不再犯该错)
- `minimize_failure(task_result, trace_events, process_verification)`:
  - 定位**首个**偏离事件(优先用 ProcessVerifier 的 evidence_offsets
    最低序号;不属于任何 violation 时用失败前的策略转折点,规则见
    design 阶段调研);
  - 截取 prefix + 环境状态,生成最小 bad case(而不是保存完整 42 步
    任务)。

### 2.2 Harness Regression Corpus 分层

- 数据集两层:
  - **E2E Corpus**(现有 corpus.py):真实 coding tasks,回答「整体
    能不能做成」;
  - **Harness Regression Corpus**(新增):最小 bad cases /
    trajectory prefixes,回答「这个 Harness bug 有没有修好」。
- 回归任务将来优先以 `TrajectoryPrefixCase` 形式进入,而不是完整
  大型任务;现有 E2E 回流机制保留。
- corpus 契约(防泄漏、gold 隔离)沿用现有 `corpus.py` 的严格校验
  思想;探针任务同样必须可复现(host 侧环境快照契约需在 design 阶段
  与现有 isolation/preflight 对齐)。

## 3. 验收准则(后续阶段,占位)

- [ ] `minimize_failure` 在合成轨迹上定位首错(已知答案用例)并截出
      正确 prefix;环境状态与可接受/禁止动作可序列化。
- [ ] `TrajectoryPrefixCase` 严格契约 + JSON round-trip + 防泄漏
      校验(不携带 gold / verifier 路径)。
- [ ] Harness Regression Corpus 入库/校验函数与现有 corpus 风格对齐。
- [ ] 现有 failure triage → regression 链路零改动。

## 4. 非目标(后续阶段)

- 不重写现有「失败 → triage → regression corpus」链路(在其旁边
  增加探针层)。
- 不引入 LLM Judge 做归因(确定性规则与人工审查)。
- 不做探针执行器(V1 先定义用例形态与生成,执行复用现有 worker 链路
  或留待评估)。

## 5. 依赖与开放问题

- 依赖 `08-29-process-verifier` 的 evidence_offsets 作为首错候选;
  需在实施时确认真实轨迹上 violation 覆盖率先达标(否则首错定位
  退化)。
- 开放:环境状态快照的粒度与可复现边界(与 Docker 隔离契约对齐);
  设计阶段调研后定案。