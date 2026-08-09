# Usage 所有权

## Goal

以 `UsageLedger`、不可变 `UsageSnapshot` 和 `BudgetPolicy` 取代 Agent token counters 与 UsageObserver→Agent 同步，让模型响应、子 Agent、Skill fork 和 Dream 的全部用量只写入一个 Owner。

## Background

- 前三个 State Ownership 子任务已完成 Session/Cancellation、Permission 与 PlanRuntime；Usage 是父迁移最后一个实现切片。
- Agent 当前保存七个可写字段：`total_input_tokens`、`total_output_tokens`、`total_cache_read_tokens`、`total_cache_creation_tokens`、`last_input_token_count`、`current_turns`、`last_api_call_time`。
- UsageObserver 自己又保存累计 totals、last usage、response count 与时间；`sync_usage_from_observer()` 每次把 Observer totals 覆盖回 Agent。
- 子 Agent、Skill fork 与 Dream 不经过 Observer，而是直接 `+=` Agent input/output counters；后续 Observer 同步可能覆盖这些 child additions。
- 预算和展示规则散落在 Agent `_get_current_cost_usd()` / `_check_budget()` / `show_cost()`，Runtime、Autonomy、Application 与 TUI 都消费不同形状的可变字段或 dict。

## Requirements

### USAGE-1：唯一 Ledger 与不可变 Snapshot

- 新增 `UsageLedger`，是一个 Agent composition 中唯一拥有累计用量、最近模型调用和 turn 状态的 mutable Owner。
- 新增 frozen `UsageSnapshot`，至少暴露 input/output/cache read/cache write/reasoning、turns、responses、last prompt tokens、last response time、估算 cost 与 Provider reported cost。
- 估算 cost 保持当前预算公式：基础输入 $3/Mtok、cache read $0.3/Mtok、cache write $3.75/Mtok、输出 $15/Mtok；它是从 token totals 计算的 derived value，不作为第二份 mutable state。
- Provider reported `Usage.cost.total` 继续累计为独立只读字段，不替代现有预算估算语义。

### USAGE-2：所有 mutation 通过 Ledger command

- 模型终态通过 `record_model_usage()` 记录；它更新 totals、response count、last prompt tokens 与 last response time。
- 子 Agent、Skill fork 与 Dream 通过 `record_child_usage()` 记录返回的 input/output，不直接修改 Agent。
- Core tool turn 通过 `record_turn()` 计数；Session clear/restore 通过 `reset()`；compaction/Plan context reset 通过窄命令清理 context-window prompt tracking。
- 禁止 Agent、Observer、Runtime、SessionLifecycle、Dream 或测试直接写 Ledger 内部字段。

### USAGE-3：Observer 与同步链删除

- `UsageObserver` 只负责把 Assistant `MessageEndEvent` 适配为 Ledger command，不再持有 totals、last usage、response count 或可变用量快照。
- 删除 `sync_usage_from_observer()`、`_last_synced_core_response_count`、`UsageStateHost` 计数字段和 Agent `_usage_observer` 兼容 facade。
- Observer 重建必须继续指向同一个 Ledger；terminal output 切换与 observer lifecycle 不能替换累计用量 Owner。

### USAGE-4：BudgetPolicy 与消费者

- 新增 frozen `BudgetDecision` 与 `BudgetPolicy(max_cost_usd, max_turns)`；Policy 只读取 UsageSnapshot，不拥有或修改 usage。
- Runtime 在 tool turn 边界先 `record_turn()`，再用 BudgetPolicy 检查当前 snapshot；Autonomy loop 使用同一 Policy，不保留第二套 token/cost 判断。
- `max_cost_usd` 与 `max_turns` 由 BudgetPolicy 保存；Core harness 和 Autonomy tick limit 读取同一配置。
- Agent `get_token_usage()`、Application `token_usage()` 返回 `UsageSnapshot`；TUI、show_cost、run/run_once 和 ContextManager 读取 snapshot 属性，不再读取 dict 或 counters。

### USAGE-5：现有产品行为不变

- 同一模型响应只累计一次；非 Assistant 或非 MessageEnd 事件不累计。
- last prompt tokens 优先使用 Provider `total_tokens`，缺失时仍按 input + cache read + cache write + output 计算。
- `max_turns` 与 `max_cost` 的停止时机、stop reason 和 notice 文案保持不变。
- run/run_once 返回的 token/cost/turns 仍是本次调用相对累计 Ledger 的差值。
- `/clear` 和 restore 清零当前 Session usage；普通 compaction 与 Plan context reset 只清 last prompt tokens，不清累计 totals 或 last response time。
- child/Skill/Dream usage 累计到父 Ledger，同时不增加父模型 response count、tool turns 或 last prompt tokens。
- TUI status 和 `/cost` 展示字段、cache hit rate 与预算/turn limit 信息保持不变。

### USAGE-6：架构与范围

- runtime boundary spec 补齐 Usage signatures、ownership contract、validation matrix、cases、tests 与 wrong/correct 示例。
- 架构测试阻止七个 Agent counters、`UsageStateHost`、同步 helper、stateful UsageObserver、Ledger 外内部写入和 child direct counter mutation 回归。
- Core 与 Provider 不得依赖新的 Usage runtime module；不新增第三方依赖、兼容字段、fallback 参数或双写阶段。

## Acceptance Criteria

- [ ] Agent composition 中只构造一个 UsageLedger 和一个 BudgetPolicy；Agent 不再保存七个 usage counters。
- [ ] UsageObserver 无累计状态，只把每个合法 Assistant terminal event 写入 Ledger 一次。
- [ ] 模型、子 Agent、Skill fork 与 Dream 的累计均出现在同一 UsageSnapshot，且不会互相覆盖。
- [ ] AgentRuntimeCoordinator 不再接收 UsageStateHost，也没有 sync response cursor；所有 read/write 走 Ledger snapshot/command。
- [ ] BudgetPolicy 同时服务 Core tool boundary 与 Autonomy，保持 max_cost/max_turns 行为和 stop reason。
- [ ] clear/restore、compaction、Plan reset、run/run_once delta、Application/TUI 与 `/cost` 均有 focused regression coverage。
- [ ] 架构测试能捕获旧 counters、Observer state、同步 helper、Ledger 外写入和 Core/Provider 反向依赖。
- [ ] focused tests、全量 pytest、compileall、Import Linter、Ruff/mypy baseline、task validate 与 task-scoped `git diff --check` 全部通过。

## Out of Scope

- Provider pricing catalog、按模型动态定价、账单对账或外部 usage persistence。
- ProviderManager、ReadFreshnessTracker、Memory owner 或前三个 ownership 切片再设计。
- 改变 Core `Usage` wire schema、JSONL session schema、CLI 参数或预算默认值。
- 全局跨 Session/cross-project 用量统计。
