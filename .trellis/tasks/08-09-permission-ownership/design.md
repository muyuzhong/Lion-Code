# Permission 所有权设计

## 1. Domain Types

新增 `lion_code/permission_state.py`：

```python
PermissionMode = Literal[
    "default",
    "acceptEdits",
    "bypassPermissions",
    "dontAsk",
    "plan",
    "auto",
]

class PermissionView(Protocol):
    @property
    def mode(self) -> PermissionMode: ...
    def is_confirmed(self, value: str) -> bool: ...

class PermissionConfirmationSink(Protocol):
    def confirm(self, value: str) -> None: ...

@dataclass(slots=True)
class PermissionState:
    mode: PermissionMode
    confirmed_values: set[str] = field(default_factory=set)

class PermissionController:
    ...
```

`PermissionState` 不离开 Controller 的所有权边界。Controller 同时结构化满足只读 View 与窄 confirmation command；只有 Agent 内的 Plan 过渡逻辑持有完整 Controller。

`confirmed_values` 取代 `_confirmed_paths`：当前缓存 key 可能是 `use tool: <name>`、危险命令文本或新文件理由，不保证是路径。该命名修正不改变缓存行为。

## 2. Composition and Data Flow

```text
                   PermissionState
                         ^
                         |
               PermissionController
                 /                 \
        PermissionView      confirmation command
               |                    |
         ToolContext          PermissionMiddleware
               |
         live read per call
```

Agent 构造流程：

1. 根据构造参数创建 PermissionState。
2. 创建 PermissionController 并由 Agent 保存 Controller 引用用于 Plan 过渡。
3. ToolContext 只接收 `PermissionView`。
4. PermissionMiddleware 构造时只接收 `PermissionConfirmationSink`，不接收可改 mode 的完整类型。

## 3. Read and Mutation Boundaries

- `Agent.permission_mode` 是只读 facade，返回 `controller.mode`。
- Plan toggle / enter / exit 暂时仍由 Agent 编排，但所有 mode 变化调用 `controller.set_mode()`。
- `_execute_tool_call()` 删除 permission 同步，只保留当前切片外的 Plan path 同步。
- PermissionMiddleware 使用 `context.permission.mode` 与 `context.permission.is_confirmed()`。
- 用户确认通过且 mode 允许缓存时，Middleware 调用窄 `confirm(value)` command。
- SessionLifecycle、SessionMemoryCoordinator、SubagentFactory 与 Application 读取 `PermissionView` 或 Agent facade，不拿 PermissionState。

## 4. Policy Boundary

`PermissionPolicy` 仍是无状态决策器，不成为 mutable permission owner：

- 输入：Tool、arguments、PermissionMode、Plan file path。
- 输出：不可变 PermissionDecision。
- 显式 deny 与 Plan hard boundary 继续优先。
- Controller 不吸收 policy rules、UI confirmation 或 Plan state。

这保持了 State ownership 与 policy evaluation 的关注点分离。

## 5. Plan Migration Boundary

本切片不会创建 PlanRuntime。现有 Plan 逻辑继续拥有：

- `_pre_plan_mode`
- `_plan_file_path`
- `_plan_approval_fn`
- `_pending_core_context_reset`
- Plan prompt 与 enter/exit transaction

唯一变化是 mode 的 read/write 改走 PermissionController。这样下一个 PlanRuntime 子任务可以直接接收现成 Controller，而无需再次迁移 Permission state。

## 6. Public and Host Contracts

- Agent 构造参数类型改为 PermissionMode；调用形状不变。
- Application/TUI 的 `permission_mode` 仍是只读字符串语义，可收紧为 PermissionMode 类型。
- SubagentFactoryHost 的 child mode 返回 PermissionMode。
- Runtime/Memory host protocol 不声明可写 permission 字段，改为只读 view/property。
- 旧字段和 ToolContext 参数直接删除，不保留 alias 或 fallback。

## 7. Invariants and Architecture Enforcement

- PermissionState 只在 composition root 构造一次。
- 除 `permission_state.py` 内 Controller 外，没有 `.mode =` 或 `confirmed_values.add()`。
- Agent 没有 `permission_mode` 实例字段和 `_confirmed_paths`。
- ToolContext 没有 `permission_mode` / `confirmed_paths`。
- PermissionMiddleware source 不包含 `set_mode` 或直接 state mutation。
- Plan mode 变化后，既有 ToolContext 不经 replace/sync 即读到新 mode。

## 8. Rollback

无数据迁移、配置迁移或新依赖。回滚点是该子任务的单一中文提交，连同 spec、架构断言和机械 fixture 更新一起回滚。
