# PlanRuntime 所有权

## Goal

以 `PlanState`、`PlanView` 和 `PlanRuntime` 取代 Agent 与 ToolContext 中散落的 Plan 字段和手工同步，让进入、退出、审批、上下文重置与会话 clear 成为一个单一 Owner 执行的事务。

## Background

- Session/Cancellation 与 Permission 所有权切片已经完成。`ToolContext.session`、`cancellation`、`permission` 均是实时 View，Plan 仍是最后一个需要手工同步的 ToolContext 状态。
- Agent 当前保存 `_pre_plan_mode`、`_plan_file_path`、`_plan_approval_fn`、`_pending_core_context_reset`，并在构造、toggle、内部 Plan 工具、工具执行和 SessionLifecycle 中分别写入。
- `ToolContext.plan_file_path` 是 Plan path 的可写镜像；`PermissionMiddleware` 每次决策读取该副本，Agent 在 `_execute_tool_call()` 前补一次同步。
- Plan 退出不仅修改一个字段，还必须恢复权限、重建系统提示、处理审批选择、保留或清理 plan path，并在 clear-and-execute 时安排 Core context reset。该事务必须由一个 Owner 保证不变量。

## Requirements

### PLAN-1：唯一状态与只读 View

- 新增 `PlanStatus`，精确表示 `inactive` / `active`。
- 新增 `PlanState`，只保存 `status`、`file_path: Path | None`、`previous_permission_mode` 与 `pending_context_reset`。
- 新增只读 `PlanView`，向 ToolRuntime 暴露实时 `is_active` 与 `file_path`；不得暴露 mutable state 或 Plan 命令。
- `PlanRuntime` 是构造完成后唯一允许修改 `PlanState` 的业务 Owner。

### PLAN-2：完整事务归属

- `PlanRuntime` 负责初始 Plan 模式、toggle、内部工具 enter/exit、Plan prompt/path 生成、审批回调和审批选择处理。
- 进入 Plan 时原子保存原权限、切换为 `plan`、生成当前 Session 的 plan path、刷新系统提示并发送 notice。
- 退出 Plan 时原子恢复目标权限、清理 previous mode/path、恢复基础提示；`keep-planning` 与审批异常必须保持 active state 不变。
- `clear-and-execute` 由 PlanRuntime 记录 pending context reset；只有 Core context reset 成功完成后才清除该 pending state。
- 所有 Permission mode mutation 继续调用 `PermissionController.set_mode()`；PlanState 不包含 PermissionState，也不直接写 PermissionState。

### PLAN-3：ToolContext 与跨层端口

- `ToolContext` 删除 `plan_file_path`，改为必填 `plan: PlanView`。
- `PermissionMiddleware` 每次调用读取 `context.plan.file_path`，不得缓存路径，也不得接收 PlanRuntime。
- `_execute_tool_call()` 删除 Plan path 同步。
- SessionLifecycle 和 AgentRuntimeCoordinator 只能调用 PlanRuntime 命令或读取窄属性，不直接写 PlanState。
- Agent 保留兼容的业务入口（`toggle_plan_mode()`、`set_plan_approval_fn()` 和内部工具 controller 方法），但这些入口只是 PlanRuntime 的薄委托。

### PLAN-4：现有产品行为不变

- 构造时 `permission_mode="plan"` 继续立即生成 plan path 并启用 Plan prompt；无原模式可恢复时退出到 `default`。
- toggle 退出恢复进入前的六种 PermissionMode；重复 enter/非 Plan exit 返回当前既有提示，不改变状态。
- 审批选择保持：`keep-planning` 留在 Plan；`execute` / `clear-and-execute` 进入 `acceptEdits`；其他选择恢复进入前模式。
- 没有审批回调的子 Agent 直接退出并恢复原模式，不伪造用户批准。
- Plan 文件不存在时仍使用 `(No plan file found)`；读取错误继续向调用方传播，不吞掉异常。
- `/clear` 在 active Plan 下为新 Session 重新生成 plan path 并保持 Plan prompt/权限；restore 仅清理 pending context reset，保持现有 active path 行为。
- clear-and-execute 继续让 exit tool 返回 `terminate=True`，随后把 Approved Plan 作为唯一活跃 Core context 持久化并继续执行。
- 动态基础提示刷新后，inactive 使用新基础提示，active 仍保留基于新基础提示构造的 Plan prompt。

### PLAN-5：架构与范围

- 在 runtime boundary spec 中补齐 Plan signatures、ownership contract、validation matrix、cases、tests 与 wrong/correct 示例。
- 增加架构测试，阻止 Agent Plan 字段/事务方法、`ToolContext.plan_file_path`、PlanRuntime 外 PlanState mutation、Agent/SessionLifecycle 直接 `PermissionController.set_mode()` 和手工同步回归。
- Core 与 Provider 不得依赖 `plan_runtime`；不新增第三方依赖、兼容字段、fallback 参数或双写过渡期。

## Acceptance Criteria

- [ ] Agent composition 中只有一个 PlanState；构造完成后只有 PlanRuntime 写入。
- [ ] `ToolContext` 只有 `plan: PlanView`，现有实例能实时看到 enter/exit/clear 后的 path 变化。
- [ ] Agent 不再保存 `_pre_plan_mode`、`_plan_file_path`、`_plan_approval_fn` 或 `_pending_core_context_reset`。
- [ ] Agent、SessionLifecycle 和 AgentRuntimeCoordinator 不直接修改 PlanState 或 Permission mode；都通过 PlanRuntime 命令完成事务。
- [ ] toggle、工具 enter/exit、全部审批分支、初始 Plan、无审批回调、missing plan file、clear、restore 与 clear-and-execute 均有 focused regression coverage。
- [ ] clear-and-execute 的 pending reset 在持久化/重放/运行时 reset 全部成功前不会被提前清除。
- [ ] 架构测试能捕获旧镜像字段、ToolContext path 双写、PlanRuntime 外 state mutation 和 Plan 外 Permission command。
- [ ] focused tests、全量 pytest、compileall、Import Linter、Ruff/mypy baseline、task validate 与 task-scoped `git diff --check` 全部通过。

## Out of Scope

- UsageLedger / UsageSnapshot / BudgetPolicy；该工作属于下一个子任务。
- ProviderManager、ReadFreshnessTracker、Memory owner 或 Session/Cancellation/Permission 再设计。
- 改变 Plan 文件格式、默认目录、Plan prompt 文案、TUI 审批选项或 PermissionPolicy 规则。
- 将 Plan 持久化到 JSONL 或在 resume 时恢复历史 PlanState。
