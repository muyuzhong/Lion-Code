# Usage 所有权设计

## 1. Domain Types

新增 `lion_code/usage.py`：

```python
@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    turns: int = 0
    responses: int = 0
    last_prompt_tokens: int = 0
    last_response_at: float | None = None
    cost_usd: float = 0.0
    reported_cost_usd: float = 0.0

@dataclass(frozen=True, slots=True)
class BudgetDecision:
    exceeded: bool
    kind: Literal["max_cost", "max_turns"] | None = None
    reason: str = ""

class BudgetPolicy:
    ...

class UsageLedger:
    ...
```

Snapshot 是跨层唯一 read model。`cost_usd` 由 totals 按现有固定公式计算；`reported_cost_usd` 是 Provider 报告值累计。二者语义明确，避免把估算值伪装成账单。

## 2. Owner and Event Flow

```text
Assistant MessageEnd ──> UsageObserver ── command ──┐
                                                    |
SubAgent / Skill / Dream ─ record_child_usage ─────> UsageLedger
                                                    |
Core tool boundary ─────── record_turn ────────────┘
                                                    |
                                             UsageSnapshot
                                           /       |       \
                                   BudgetPolicy  Context   UI/App
```

UsageObserver 不再是 state owner，只是 Core event adapter。Observer 重新订阅时接收 composition root 创建的同一个 Ledger，因此 observer lifecycle 与 usage lifecycle 解耦。

## 3. Ledger Commands and Invariants

- `record_model_usage(usage, response_at=None)`：复制并累计 Provider usage，递增 responses，更新 last prompt/time。
- `record_child_usage(input_tokens, output_tokens)`：只累计父账本的 input/output；不修改 responses、turns、last prompt/time。
- `record_turn()`：只递增 tool-loop turns。
- `reset()`：清除当前 Session 的全部 usage state。
- `reset_context_tracking()`：只把 last prompt tokens 归零；保留 totals、turns、responses 与 last response time。
- `snapshot()`：返回 frozen primitives，外部无法 alias 或修改 Ledger。

所有内部 counters 都封装在 UsageLedger 中；其他模块只能调用命令或读取 snapshot。

## 4. Budget Boundary

BudgetPolicy 保存构造参数 `max_cost_usd` 与 `max_turns`，并提供：

```python
def check(self, usage: UsageSnapshot) -> BudgetDecision: ...
```

判断顺序与现有 Agent 相同：先 max_cost，后 max_turns。Runtime 在每次 tool calls 前先递增 turn 再 check；Autonomy 的每个 budget checkpoint 读取同一 Ledger snapshot/Policy。Policy 不记录已超限状态，stop reason 仍由 Runtime/Autonomy 当前流程设置。

## 5. Runtime Composition

Agent construction：

1. 创建 `UsageLedger`。
2. 创建 `BudgetPolicy(max_cost_usd, max_turns)`。
3. 将二者传给 AgentRuntimeCoordinator 和 AutonomyRuntime。
4. LionAgentRuntime 的 Core `max_turns` 读取 BudgetPolicy 配置。
5. UsageObserver 每次重建都接收同一个 Ledger。

`UsageStateHost` 删除。原本混在该 host 中的 `effective_window` 属于 model/context runtime，不属于 Usage；将其归入现有 Runtime identity/context host 访问，不进入 Ledger。

## 6. Consumer Migration

- `Agent.get_token_usage()` 返回 `self._usage.snapshot()`；不提供旧 counter properties。
- `show_cost()` 使用一个 snapshot 完成 token、cache、cost、turn 展示，避免同一输出读取多个时点。
- `AgentRuntimeCoordinator.run()` / `run_once()` 在调用前后取 snapshot 并计算 delta。
- ContextRuntimeState 读取 snapshot 的 last prompt/time；compaction/reset 调用 Ledger 的 context tracking command。
- SessionLifecycle clear/restore 调用 `ledger.reset()`。
- Agent child/skill 与 Dream 使用 Ledger command 记录 child result。
- LionCodingSession 与 TUI 改为 typed UsageSnapshot 属性访问。
- SessionMemoryCoordinator host 删除未使用的 token counter 字段。

## 7. Observer Boundary

`UsageObserver` 只保存一个 Ledger command reference，不保存 UsageTotals、last Usage、response count 或 timestamps。现有 Observer tests 拆为：

- UsageLedger command/snapshot tests。
- UsageObserver event filtering与单次 forwarding tests。
- Runtime observer rebuild tests证明 Ledger identity/totals 保持。

`sync_usage_from_observer()` 与 response cursor 彻底删除，不留 shim。

## 8. Invariants and Architecture Enforcement

- UsageLedger 和 BudgetPolicy 只在 Agent composition root 构造一次。
- 七个旧 Agent counter 名称不出现在生产代码。
- Ledger 内部字段赋值只存在于 `usage.py`。
- UsageObserver 没有 totals/last usage/response count state。
- Child usage 只调用 `record_child_usage()`；Runtime 只调用 Ledger commands/read snapshot。
- Core/Provider 不导入 `lion_code.usage` 或 observers。
- Snapshot 是 frozen，任何 UI/Application consumer 都不接收 mutable Ledger。

## 9. Rollback

没有持久化、配置或 wire migration，也不新增依赖。回滚点是一个中文实现提交；spec、架构断言和消费者迁移与实现一同回滚，禁止保留双写兼容层。
