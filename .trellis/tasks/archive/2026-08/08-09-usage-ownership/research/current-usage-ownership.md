# 当前 Usage 状态所有权与迁移清单

## Mutable State and Mirrors

### Agent counters

`lion_code/agent.py:177-183` 保存七个 usage 字段：四个累计 token、最近 prompt tokens、tool turns 与最后模型调用时间。Agent 还保存 `max_cost_usd` / `max_turns` 并实现 cost 与 budget 规则。

### UsageObserver

`lion_code/observers/usage.py` 同时保存 UsageTotals、last Usage、last response time 与 response count。它已是一个完整累计 owner，但 Runtime 又把它同步到 Agent。

### Synchronization

`lion_code/agent_runtime.py:290-319` 的 `sync_usage_from_observer()` 每次把 Observer totals 覆盖到 Agent counters，并用 `_last_synced_core_response_count` 避免重复刷新 last prompt/time。

同步发生在 context prepare、tool calls 前、compaction、Plan context reset 与 run 结束路径。Session clear/restore 既重建 Observer 又清 Agent counters/cursor。

## Writers Outside Observer

- Skill fork：`agent.py:1155-1156` 直接把 child run_once tokens 加到 Agent。
- agent tool：`agent.py:1182-1183` 直接累加。
- Dream：`dream.py:547-548` 直接累加父 Agent。
- Runtime：tool calls 前直接 `current_turns += 1`；clear/restore、compaction、Plan reset 分别写多个 Agent fields。

这些写入不会进入 Observer totals，下一次同步会把 child addition 覆盖掉，是当前最关键的所有权缺陷。

## Readers

- ContextManager：`effective_window`、`last_input_token_count`、`last_api_call_time`。
- AgentRuntimeCoordinator：run/run_once 前后差值、AgentRunResult、tool budget gate。
- Agent：get_token_usage dict、show_cost、cache hit rate、估算 cost、budget decision。
- AutonomyRuntime：三个 checkpoint 调 `_check_budget()`，并读取 max_turns 作为 loop tick limit。
- Application/TUI：token usage dict 的 `input` / `output`。
- SessionMemoryHost 声明 input/output counters，但当前实现不读取，属于泄漏协议。

## Preserved Behavior Matrix

| Path | Required behavior |
|---|---|
| Assistant terminal Usage | 累计全部 token/reasoning/reported cost，responses +1 |
| Non-assistant/non-terminal event | 不累计 |
| Provider total_tokens 缺失 | last prompt 使用 input+cache read+cache write+output |
| Child/Skill/Dream result | 只累计父 input/output，不改父 response/turn/last prompt |
| Tool calls boundary | turns +1 后执行 max_cost→max_turns check |
| run/run_once | 返回调用期间 Ledger delta |
| `/clear` / restore | 清当前 Session 全部 usage |
| Normal compaction / Plan reset | 仅 last prompt tokens 归零 |
| Observer rebuild / terminal toggle | 累计 Ledger identity 与 totals 不丢失 |
| `/cost` / TUI status | 保持现有估算、cache hit 与 in/out 展示 |

## Existing Coverage and Gaps

- `tests/runtime/test_usage_observer.py` 覆盖 Observer totals/snapshot/last usage 与 sync helper，但没有 child overwrite 回归。
- `tests/integration/test_agent_core_runtime.py` 覆盖 turn/max_cost、clear counters、last prompt reset 和 cost；大量断言仍直接读写 Agent counters。
- `tests/test_agent_run.py` 覆盖 structured result delta；`tests/test_dream.py` 覆盖 direct parent additions。
- `tests/application/test_coding_session.py` 直接检查 `_usage_observer` identity/response count；TUI 使用 dict。
- 架构测试尚未禁止 Agent counters、sync helper、stateful Observer 或 Ledger 外 mutation。

## Implementation Boundary

- 新文件：`lion_code/usage.py`。
- 核心生产文件：`agent.py`、`agent_runtime.py`、`observers/usage.py`、`session_lifecycle.py`、`autonomy_runtime.py`、`dream.py`、`application/session.py`、`tui/app.py`。
- 协议/fixture：`agent_lifecycle.py`、`session_memory_coordinator.py`、runtime/integration/application/tui/dream/autonomy/architecture tests。
- 明确不动：Core Usage wire schema、Provider usage parsing、JSONL、pricing catalog、Memory/Plan/Permission/Session owner。
