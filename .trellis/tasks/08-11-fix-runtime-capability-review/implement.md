# 执行计划

1. [x] 记录当前工作区状态，确认只触碰本任务文件、两个生产模块和对应测试；复核 `prd.md`、`design.md` 及 backend spec。
2. [x] 在 `AgentRuntimeCoordinator` 组装处移除 Coordinator-owned Harness 的通用 `max_turns` 传递；新增排队 follow-up 回归，证明最终文本不会消耗 Usage turn 预算。
3. [x] 在 `LionAgentRuntime` 增加可选 `cancel_callback` 命令路由，并由 Coordinator 注入 `ExecutionControl.cancel`；新增外部 cancellation view 的运行中取消回归。
4. [x] 在 `CapabilitySpec.__post_init__` 归一化 tuple/frozenset 容器；新增外部 list/set 变更不影响 spec、Registry 顺序和聚合的回归。
5. [x] 将 `_FakeToolSource` 改为返回 `LionTool` 序列，更新名称断言，确保测试 fake 满足 `ToolSource` 协议。
6. [x] 运行受影响测试和静态检查：
   - `python -m pytest -q tests/runtime/test_agent_runtime.py tests/integration/test_agent_core_runtime.py tests/capabilities/test_capability_registry.py`
   - `python -m pytest -q tests/test_usage.py tests/core/test_cancellation.py tests/runtime/test_usage_observer.py`
   - `ruff check lion_code/agent_runtime.py lion_code/capabilities tests/runtime/test_agent_runtime.py tests/integration/test_agent_core_runtime.py tests/capabilities/test_capability_registry.py`
   - `ruff format --check` 对上述 Python 文件执行
   - `mypy lion_code/capabilities tests/capabilities`，确认新增 Capability 类型错误消失并区分既有基线错误
   - `python -m compileall -q lion_code tests`、`lint-imports --no-cache`、`git diff --check`
7. [x] 按 backend quality/runtime/capability 规范做一次全范围检查；若发现问题，修复后重复检查。
8. [x] 只 stage 本次生产文件、测试文件和任务规划文件，使用中文描述提交；不得带入工作区已有无关改动。

## 风险与回滚点

- 风险：移除 Coordinator 的通用 `max_turns` 后，队列中的文本 follow-up 可能暴露测试未覆盖的循环行为；回归测试须至少包含 tool -> final text -> follow-up 三段路径。
- 风险：外部取消回调若注入错误 Owner，会使取消路径失效；测试必须断言 callback 和共享 `ExecutionControl` 的身份/状态。
- 回滚点：所有生产与测试改动集中在一个中文提交；如果全范围验证暴露非本任务问题，保留失败证据并不修改无关基线。
