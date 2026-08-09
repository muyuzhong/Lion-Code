# PlanRuntime 所有权设计

## 1. Domain Types

新增 `lion_code/plan_runtime.py`：

```python
PlanStatus = Literal["inactive", "active"]

class PlanView(Protocol):
    @property
    def is_active(self) -> bool: ...
    @property
    def file_path(self) -> Path | None: ...

@dataclass(slots=True)
class PlanState:
    status: PlanStatus = "inactive"
    file_path: Path | None = None
    previous_permission_mode: PermissionMode | None = None
    pending_context_reset: str | None = None

@dataclass(frozen=True, slots=True)
class PlanToolOutcome:
    content: str
    terminate: bool = False

class PlanRuntime:
    ...
```

`PlanState` 不离开 Runtime 的所有权边界。`PlanView` 只暴露 PermissionPolicy 所需的实时 path 与派生的 active 状态，不暴露 previous mode、pending reset 或 mutation。

## 2. Composition and Data Flow

```text
                     PlanState
                         ^
                         |
                    PlanRuntime
             / command   |       \ command
            /            |        \
      Agent facade   PlanView   PermissionController
                         |               |
                    ToolContext      PermissionState
                         |
                 PermissionMiddleware
```

Agent composition root 创建一个 `PlanState` 和 `PlanRuntime`，并把同一个 Runtime 作为结构化满足 `PlanView` 的对象传给 ToolContext。PlanRuntime 持有完整 PermissionController；ToolRuntime 只获得 PlanView 和 PermissionView。

## 3. Transaction Boundary

PlanRuntime 接收最窄的宿主能力：读取当前 Session id 与基础提示、设置当前系统提示、发送 notice。它内部完成以下事务：

- `initialize()`：构造参数已是 Plan mode 时建立 active state/path/prompt。
- `toggle()`：同步 enter 或无审批 exit，返回实际 PermissionMode。
- `enter()`：供内部工具进入 Plan，并返回当前既有文案。
- `exit()`：读取 plan 文件、调用审批回调、处理 choice，返回 `PlanToolOutcome`。
- `reset_for_new_session()`：清理 pending reset；active 时为新 Session 重建 path/prompt。
- `reset_after_restore()`：只清理 pending reset，保持现有 active path 行为。
- `complete_context_reset()`：仅在 Recorder compaction、repository replay 和 Core runtime reset 都成功后清除 pending state。
- `refresh_prompt()`：基础提示变化后按当前 active 状态重建当前系统提示。

状态字段只在这些命令内部变化；调用方不分解事务步骤。

## 4. Permission Boundary

Plan 与 Permission 是相邻但独立的 Domain：

- PlanState 只记住进入前的 `PermissionMode`，不嵌套 PermissionState。
- PlanRuntime 通过 `PermissionController.mode` 读取，通过 `set_mode()` 写入。
- ToolRuntime 独立通过 PermissionView 读取实时权限，通过 PlanView 读取实时 plan path。
- 架构门禁将 `PermissionController.set_mode()` 的业务调用收紧到 `plan_runtime.py`；Agent 与 SessionLifecycle 不再持有 Plan transition 写权限。

## 5. Prompt and Approval Boundary

- Plan prompt/path 生成从 Agent 迁到 PlanRuntime；默认路径仍为 `~/.claude/plans/plan-<session-id>.md`，文案不变。
- `_plan_approval_fn` 从 Agent 字段迁为 Runtime 配置。`Agent.set_plan_approval_fn()` 是薄委托，Application/TUI API 不变。
- `keep-planning` 或 approval callback 抛错时，Runtime 不提前改 mode/path/prompt，保证重试安全。
- PlanRuntime 不拥有基础系统提示本身；它只在事务边界调用宿主的 prompt setter，因此不扩大到 Provider/Thinking/MCP prompt ownership。

## 6. Pending Context Reset

`pending_context_reset` 属于 PlanState，因为它由 `clear-and-execute` 产生并决定退出工具是否终止当前 loop。

AgentRuntimeCoordinator 读取 Runtime 的只读 pending 值，完成：

1. Recorder 写入 compaction。
2. Repository 重放确认只剩一个 UserMessage。
3. Core runtime 重置 active context。
4. 同步 usage/context flags。
5. 调用 `PlanRuntime.complete_context_reset()`。

任一步失败都不清除 pending，允许错误被显式观察和恢复，不产生“状态已消费但上下文未切换”的半事务。

## 7. Lifecycle and Tool Contracts

- `ToolContext.plan_file_path` 直接删除，替换为 `plan: PlanView`。
- PermissionMiddleware 将 Path 作为 plan domain value 传给 PermissionPolicy；Policy 比较时只做边界字符串转换。
- SessionLifecycle host 不再声明 Plan 私有字段、path/prompt helper；改为只持有 `plan: PlanRuntime` 命令端口。
- `_execute_tool_call()` 不再同步任何 Plan 状态。
- 内部 enter/exit 工具继续通过 AgentToolController 调用 Agent 薄委托，避免 ToolRuntime 获得完整 PlanRuntime。

## 8. Invariants and Architecture Enforcement

- PlanState 只在 Agent composition root 构造一次。
- 除 `plan_runtime.py` 外没有 PlanState 字段写入。
- Agent 没有四个旧 Plan 字段和旧 Plan transaction helper。
- ToolContext 没有 `plan_file_path`，PermissionMiddleware source 只读取 `context.plan.file_path`。
- `PermissionController.set_mode()` 的业务调用只存在于 PlanRuntime。
- PlanView identity 在 enter/exit/clear 中不替换；消费者看到的是同一对象的实时状态。

## 9. Rollback

没有数据或配置迁移，也不新增依赖。回滚点是该子任务的单一中文实现提交，连同 spec、架构断言及 ToolContext fixture 机械更新一起回滚。
