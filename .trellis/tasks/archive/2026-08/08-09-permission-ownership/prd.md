# Permission 所有权

## Goal

以 `PermissionState`、`PermissionView` 和 `PermissionController` 取代 `Agent` 与 `ToolContext` 中的权限模式及确认缓存镜像，让权限消费者动态读取同一个权威状态，所有 mutation 通过明确命令完成。

## Background

- 上一切片已完成 Session/Cancellation 所有权迁移（`2b77174`），`ToolContext` 已开始从状态容器转为依赖上下文。本任务在该结构上继续，不回退已建立的 View/Controller 模式。
- `Agent.__init__` 当前直接保存 `permission_mode` 与 `_confirmed_paths`，并把两者传入 `ToolContext`（`lion_code/agent.py:142,187,218-232`）。
- `_execute_tool_call()`、Plan toggle、Plan tool enter/exit 和 clear lifecycle 会手工同步 `Agent.permission_mode -> ToolContext.permission_mode`（`lion_code/agent.py:606-629,1102-1114,1214-1302`; `lion_code/session_lifecycle.py:55-84`）。
- `PermissionMiddleware` 直接读取 `context.permission_mode` / `context.confirmed_paths`，并直接修改确认集合（`lion_code/tooling/middleware.py:102-177`）。
- `ToolContext` 把 Environment、Permission state、Plan state 和 Tool execution state 混在同一 dataclass（`lion_code/tooling/context.py:40-67`）。
- 子 Agent permission mode、Session Memory、application/TUI 和 Plan 逻辑均从 Agent 字符串字段读取；现有测试还通过直接赋值模拟状态变化。
- `plan_file_path` 属于 Plan Domain。本切片只让 Plan 逻辑通过 PermissionController 改变 mode；PlanState/PlanRuntime 和 `ToolContext.plan_file_path` 留给下一个子任务。

## Requirements

### PERM-1：唯一状态与类型

- 新增 `PermissionMode`，精确表示现有六种模式：`default`、`acceptEdits`、`bypassPermissions`、`dontAsk`、`plan`、`auto`。
- 新增 `PermissionState`，只保存 mode 与已确认值集合。确认项实际可能是路径、命令或工具理由，因此使用准确的 `confirmed_values` 语义，不继续传播误导性的 `confirmed_paths` 名称。
- 新增 `PermissionController`，是构造完成后唯一允许修改 PermissionState 的业务 Owner。
- Controller 提供 `mode`、`set_mode()`、`is_confirmed()` 和 `confirm()`；任何消费者都不能直接写 state 字段。

### PERM-2：读写端口分离

- 新增只读 `PermissionView`，暴露 `mode` 与 `is_confirmed(value)`。
- `ToolContext` 删除 `permission_mode` 和 `confirmed_paths`，改为必填 `permission: PermissionView`。
- `PermissionMiddleware` 通过 View 动态读取 mode/confirmation，不持有 mutable state，也不能调用 `set_mode()`。
- 确认通过后的缓存写入使用只暴露 `confirm(value)` 的窄命令端口；Middleware 不能获得完整 PermissionController 写接口。

### PERM-3：Agent 与 Plan 过渡边界

- Agent composition root 创建一个 PermissionState/PermissionController，并把同一个 View 传给 ToolContext。
- `Agent.permission_mode` 保留为只读 facade property，不保存或暴露第二份 mutable value。
- 当前仍在 Agent 内的 Plan enter/exit/toggle 必须改为调用 PermissionController.set_mode()，不得直接赋值或同步 ToolContext。
- `_execute_tool_call()` 不再执行 permission mode 同步；Middleware 每次执行都读取 live View。
- `Agent._confirmed_paths` 彻底删除。

### PERM-4：现有产品行为不变

- 六种 permission mode 的 PermissionPolicy 决策顺序和显式 deny/Plan hard boundary 保持不变。
- `default` 下同一可缓存确认理由只询问一次；`auto` mode 仍不缓存 classifier 的 confirm 决定。
- Plan 进入、退出、批准和 clear 后的 permission mode 行为保持不变。
- 子 Agent 继续继承 `plan` / `auto`，其他父模式仍映射为 `bypassPermissions`。
- Application/TUI 继续通过 `Agent.permission_mode` 只读展示当前模式。
- Hook trust 的 `dontAsk` 行为保持不变。

### PERM-5：架构与范围

- 在 runtime boundary spec 中补齐 Permission signatures、contracts、validation matrix、cases、tests 与 wrong/correct 示例。
- 增加架构测试，阻止 `Agent.permission_mode` mutable field、`Agent._confirmed_paths`、`ToolContext.permission_mode`、`ToolContext.confirmed_paths` 和 Controller 外 direct state writes 回归。
- 不新增第三方依赖，不增加兼容字段、fallback 参数或双写过渡期。

## Acceptance Criteria

- [ ] Agent composition 中只有一个 PermissionState，构造完成后仅 PermissionController 写入。
- [ ] `ToolContext` 只有 `permission: PermissionView`，不再保存 mode 或 confirmation 集合。
- [ ] PermissionMiddleware 能观察 Controller 的实时 mode 变化，无需重建或同步 ToolContext。
- [ ] Middleware 只能通过窄 confirmation command 记录已批准值，不能修改 mode。
- [ ] Agent/Plan/SessionLifecycle/SessionMemory/SubagentFactory/Application/TUI 全部从 View 或只读 facade 读取。
- [ ] default confirmation cache、auto non-cache、Plan hard boundary、Plan enter/exit/approval、child inheritance 与 dontAsk hook trust 均有 focused regression coverage。
- [ ] 架构测试能捕获旧镜像字段、ToolContext 双写和 Controller 外 PermissionState mutation。
- [ ] focused tests、全量 pytest、compileall、Import Linter、Ruff/mypy baseline、task validate 与 task-scoped `git diff --check` 全部通过。

## Out of Scope

- PlanState / PlanRuntime、Plan prompt/file/approval/context-reset 所有权迁移。
- UsageLedger、ProviderManager、ReadFreshnessTracker 或 Memory 所有权调整。
- PermissionPolicy 规则语义、配置文件格式或新增 permission mode。
- 前端新增权限选择 UI。
