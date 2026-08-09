# Session 与 Cancellation 所有权执行计划

## Implementation Checklist

1. 在 Core 增加统一的 CancellationView/CancellationToken，替换 Provider、Tool 与 Harness 的重复取消类型和私有实现。
2. 增加最小 ExecutionControl，并让 AgentRuntimeCoordinator 拥有 begin/cancel 流程。
3. 增加 SessionView/SessionIdentityState，把 Agent identity 字段改为只读 facade。
4. 把 ToolContext 改为 `session` / `cancellation` 依赖，删除 `session_id` / `cancellation_fn` 和 callback 合成路径。
5. 更新 Agent、AgentRuntimeCoordinator、SessionLifecycle、Autonomy、Session Memory、CLI/application 的读写端口。
6. 机械更新 ToolContext 测试 fixture，确保每个 fixture 显式构造 session view 与 cancellation token，不提供 fallback。
7. 增加 focused behavior tests：identity 动态读取、clear/restore single writer、共享 token、abort、timeout、tool cancellation、取消后续聊。
8. 扩展架构测试，禁止已删除字段/协议和新的 identity mirror writer。
9. 更新 `.trellis/spec/backend/runtime-boundaries.md`，写入五条 State Ownership 规则与本切片的实际 Owner。
10. 运行完整验证；检查改动文件数与依赖变化；由 Trellis check 子代理复核后修正发现。

## Focused Validation

```powershell
python -m pytest -q tests/core/test_cancellation.py
python -m pytest -q tests/tooling/test_runtime.py tests/adapters/test_tool_adapter.py
python -m pytest -q tests/runtime/test_agent_runtime.py
python -m pytest -q tests/integration/test_agent_core_runtime.py
python -m pytest -q tests/application/test_coding_session.py
python -m pytest -q tests/architecture/test_runtime_boundaries.py
```

## Full Validation

```powershell
python -m pytest -q
python -m compileall -q lion_code tests
lint-imports --no-cache
python ./.trellis/scripts/task.py validate .trellis/tasks/08-09-session-cancellation-ownership
git diff --check
```

## Review Gates

- `rg "_aborted|cancellation_fn|tool_context\.session_id" lion_code tests` 只能命中明确允许的历史/断言文本，不能命中生产状态字段。
- `rg "class (SimpleCancellationToken|ToolCancellationToken)" lion_code` 无结果。
- SessionLifecycle 之外没有 SessionIdentityState reset 调用。
- Agent 只暴露 facade property，不保存 identity 或 cancellation mutable mirror。
- 新增第三方依赖数为 0。

## Risky Files and Rollback Points

- `lion_code/core/harness.py`：Provider/Tool signal 传播；失败时优先回滚统一 token 适配，不改 loop 语义。
- `lion_code/agent_runtime.py`：abort、timeout、chat reset 与 host ports；必须以现有取消集成测试为回归基线。
- `lion_code/session_lifecycle.py`：clear/restore 与 Recorder 重建；必须保留 JSONL 和 Session Memory 不变量。
- `lion_code/tooling/context.py` / `runtime.py`：fixture 和 middleware blast radius 较大，但参数替换属于机械变更。

最终回滚点是本子任务单一中文提交；不产生数据 migration。
