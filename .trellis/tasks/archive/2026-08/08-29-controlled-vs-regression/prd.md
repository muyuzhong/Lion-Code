# PRD: 受控实验语义(Controlled vs Regression 区分)

> 来源:父任务 `08-29-eval-fidelity` 3.4 与用户第 4 点指示:
> 「给 PairedExperiment 明确分成两种语义:Controlled Experiment
> (同 code_sha,只开关能力 → 可谈因果)与 Regression Comparison
> (跨 code_sha → 只能谈版本整体是否回归)」。
> 已确认范围:**语义区分 + 接通 worker 已有注入点;compression 无
> 注入点则标注为「声明字段」写入 spec,真实开关留待后续**。

## 1. 背景与目标

PR #143 的 `PairedExperiment` 已锁定 model/provider/task/seed/budget,
但 `HarnessVariant` 目前更像「版本声明」而非「实验处理变量」:

- `agent_worker.py` 传给 factory 的只有 permission_mode / model /
  max_cost_usd / max_turns / ... **没有** prompt / tool_policy /
  compression 的任何注入;
- `build_full_coding_backend` 已支持 `custom_system_prompt` 与
  `tool_registry` 注入点,worker 未使用;
- 因此 baseline(code_sha=A, compression=v1) vs candidate
  (code_sha=B, compression=v2) 只能证明「B 版本比 A 好」,不能证明
  「compression v2 导致了提升」。

目标:让「因果评估」语义真正成立 —— 区分受控实验与跨版本回归,
并接通已存在的注入点(compression 因无运行开关,如实标注)。

## 2. 需求

### 2.1 `ExperimentKind` 语义

- `PairedExperiment` / `PairedTrial` / `PairedExperimentReport` 增加
  `experiment_kind`: `CONTROLLED` | `REGRESSION`。
- 判定规则:
  - `CONTROLLED`:baseline 与 candidate 的 `profile.agent_code_sha`
    相同(Harness 代码未变),差异仅限声明的 profile 可变字段 →
    可以谈「该机制导致的变化」;
  - `REGRESSION`:agent_code_sha 不同 → 只能谈「这个版本整体是否
    回归」。
- `build()` 校验:CONTROLLED 时除声明字段外无其他 profile 差异
  (沿用现有 invariants 校验);REGRESSION 允许 code_sha 不同,
  但 catalog/seed/budget 等其余不变量仍须相同。
- 报告与 Markdown 按 kind 区分结论措辞(如 controlled 用
  「机制导致」,regression 用「版本整体」)。

### 2.2 worker 注入点接通(已有能力)

- `run_agent_worker` 将 profile 的变异配置真正传给 factory:
  - `custom_system_prompt`:由 `prompt_version` 经映射提供
    (V1:prompt 版本 → 提示词文本的受控映射表,置于评测侧;
    无映射时不变更默认 prompt);
  - `tool_registry`:由 `tool_policy_version` 经映射提供
    (V1:tool_policy 版本 → 工具集白名单/过滤规则的受控映射;
    无映射时使用默认 registry)。
- 映射表本身版本化、可审计、落盘到 manifest extensions
  (不含敏感内容)。
- **compression**:无运行注入点 → 标注为「声明字段」:profile
  记录 compression_version,worker 不注入;spec 明确记录
  「compression 暂为声明,真实开关后续」,避免误读 causation。

### 2.3 可复核性

- PairedExperimentReport 记录两侧 agent_code_sha 与 experiment_kind,
  以及注入映射的 fingerprint,保证「声明改变真的被注入」。

## 3. 验收准则

- [ ] ExperimentKind 判定:同 code_sha + 仅声明字段差异 → controlled;
      跨 code_sha → regression;其余不变量(seed/budget/catalog)
      不同时两种 kind 都拒绝配对。
- [ ] worker:prompt_version 有映射 → factory 收到 custom_system_prompt;
      tool_policy_version 有映射 → factory 收到 tool_registry;
      无映射 → 使用默认(现有行为不变)。
- [ ] compression_version 不参与注入,spec 标注「声明字段」。
- [ ] 报告 Markdown 按 kind 渲染不同结论措辞;报告含两侧
      agent_code_sha 与注入映射 fingerprint。
- [ ] 单测覆盖:controlled/regression/无映射降级三类;现有
      test_experiment_layer.py 全部通过(不变量兼容)。
- [ ] tests/benchmarks 全绿。

## 4. 非目标

- 不建立 compression 的真实运行开关(注入点为声明,spec 记录)。
- 不做真实 prompt/tool_policy 内容(映射表 V1 可为受控占位,
  由评测侧填充真实版本资源)。
- 不做 Gate V2 与统计检验(顺延)。
- 不改 `classify_failure()` 与回流链。