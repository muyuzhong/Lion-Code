# 当前 Plan 状态所有权与迁移清单

## Current Mutable State

`lion_code/agent.py` 当前保存四个 Plan 字段：

- `_pre_plan_mode`：进入 Plan 前的 PermissionMode。
- `_plan_file_path`：当前 Session 的 Plan 文件路径。
- `_plan_approval_fn`：Application/TUI 注入的异步审批回调。
- `_pending_core_context_reset`：clear-and-execute 生成、由 Core runtime 消费的批准计划摘要。

`ToolContext.plan_file_path` 是 `_plan_file_path` 的第二份可写状态。Agent 在构造、toggle、enter/exit、clear 和每次 `_execute_tool_call()` 前手工同步。

## Writers and Transactions

### Agent construction and facade

- `Agent.__init__` 初始化四个字段，并在初始 `permission_mode == "plan"` 时生成 path/prompt。
- `set_plan_approval_fn()` 直接替换 callback 字段。
- `toggle_plan_mode()` 直接拆分执行 previous mode、PermissionController、path、prompt、ToolContext mirror 与 notice 更新。

### Internal Plan tools

- `_execute_plan_mode_tool("enter_plan_mode")` 重复实现 toggle 的 enter 事务。
- exit 分支读取 plan file，调用 approval callback，并处理 `keep-planning`、`execute`、`clear-and-execute`、manual 与无 callback 分支。
- `clear-and-execute` 写 `_pending_core_context_reset`；`exit_plan_mode_tool()` 根据该字段设置 `ToolResult.terminate`。

### Session and Core lifecycle

- `SessionLifecycle.clear_history()` 清 pending reset；active Plan 时生成新 Session path、重建 prompt，再写 ToolContext mirror。
- `SessionLifecycle.restore_core_session()` 清 pending reset，但保持当前 Plan path。
- `AgentRuntimeCoordinator.apply_pending_core_context_reset()` 读取 pending，写 compaction、重放、reset Core context，最后清 pending。

## Readers

- `PermissionMiddleware` 将 `context.plan_file_path` 传给 PermissionPolicy 的 hard boundary 与普通决策。
- `PermissionPolicy` 在 Plan mode 只允许 workspace mutation 命中当前 plan file。
- Plan prompt、notice、approval response 与 integration tests读取当前 path。
- Application/TUI 只通过 Agent setter/toggle 接口，不需要 Plan mutable state。

## Preserved Behavior Matrix

| Path | Required behavior |
|---|---|
| Initial `permission_mode="plan"` | active path/prompt；退出 fallback 到 default |
| Toggle enter/exit | 保存并恢复原 PermissionMode |
| Tool duplicate enter | 返回 Already，不改变状态 |
| Tool exit outside Plan | 返回 Not in，不改变状态 |
| Approval keep-planning | 保持 active/path/prompt/permission |
| Approval execute | 退出到 acceptEdits，不安排 context reset |
| Approval clear-and-execute | 退出到 acceptEdits，安排 reset 并 terminate 当前 tool loop |
| Approval manual/unknown | 恢复 previous mode |
| No approval callback | 恢复 previous mode，不声称用户批准 |
| Missing plan file | 审批内容使用 `(No plan file found)` |
| `/clear` active Plan | 新 Session path，Plan 权限/prompt 不变 |
| Restore | 清 pending，保留现有 active path |
| Context reset failure | pending 不得提前清除 |

## Existing Coverage and Gaps

- `tests/tooling/test_agent_runtime.py` 已覆盖 toggle、内部工具和 clear 后 PermissionView identity，但仍断言 ToolContext path mirror。
- `tests/integration/test_agent_core_runtime.py` 覆盖 clear-and-execute 的 compaction/replay/continue，但通过直接写 Agent/ToolContext 私有 path 布置状态。
- Application/TUI 已覆盖 callback wiring 和 toggle 入口，缺少独立 Plan domain transaction tests。
- 当前架构测试只保护 Permission single-writer；尚未阻止四个 Agent Plan 字段、ToolContext path mirror 或 PlanRuntime 外 Plan state writes。

## Implementation Boundary

- 新文件：`lion_code/plan_runtime.py`。
- 高风险生产文件：`lion_code/agent.py`、`lion_code/agent_runtime.py`、`lion_code/session_lifecycle.py`、`lion_code/tooling/context.py`、`lion_code/tooling/middleware.py`、`lion_code/tooling/permission.py`。
- 机械范围：所有直接构造 ToolContext 的 tests/adapters/integration/tooling fixtures。
- 明确不动：Usage counters/Budget、Memory owner、Provider config、read freshness owner、Plan 持久化格式和前端选项。
