# 收窄 Host 协议并拆分 SessionLifecycle

## Goal

将 `AgentRuntimeHost`（27 字段 + 16 方法）拆成 3-4 个窄端口，使 `AgentRuntimeCoordinator`
不再通过一个宽协议访问 Agent 的全部内部状态；同时从 coordinator（959 行）中拆出
`SessionLifecycle`，收敛 clear/restore/compact/close + recorder 的生命周期职责。

## Confirmed Facts

- `AgentRuntimeHost` 暴露 27 个字段和 16 个方法/属性，coordinator 通过 `self._host.*`
  读写全部字段；这不是窄端口而是 Agent 的结构化镜像。
- coordinator 中 `host.*` 访问有 80+ 处，按用途可分为：
  - **Usage state**：token 计数（7 字段）+ `_check_budget` / `_get_current_cost_usd`
  - **Runtime identity**：model / thinking / terminal / system_prompt + `api_configured`
    / `_create_terminal_renderer` / `_apply_core_thinking_level`
  - **Session state**：session_id / session_start_time / `_session_repository` /
    `tool_context` / `permission_mode` / `_plan_file_path` / `_base_system_prompt` /
    `_pending_core_context_reset` + `_generate_plan_file_path` / `_build_plan_mode_prompt`
  - **Memory turn**：`_memory_coordinator` / `_turn_memory_overlays` /
    `_last_memory_injection` / `_memory_injector` + 5 个 memory 方法
  - **Abort/notice**：`_aborted` / `_last_stop_reason` + `_emit_notice` / `_ensure_mcp_tools`
  - **Tool env**：`tool_environment`（仅 close 使用）
- coordinator 的 SessionLifecycle 方法：`clear_history`(871)、`restore_core_session`(900)、
  `compact`(942)、`close`(947)，加上被它们调用的 `reset_core_observers`(501) 和
  `reset_session_counters`(485)，合计约 200 行。
- `reset_core_observers` 和 `reset_session_counters` 也被 `__init__` 和 `chat()` 调用，
  不能简单移走；SessionLifecycle 需要持有引用或通过方法调用。
- coordinator 构造函数接收 1 个 `host: AgentRuntimeHost`；拆端口后改为接收多个窄协议。
- `sync_usage_from_observer(host, ...)` 是自由函数，直接读写 host 的 7 个 token 字段。

## Requirements

- R1：定义 3-4 个窄 Protocol 替代 `AgentRuntimeHost`，按实际访问模式分组（Usage state、
  Runtime identity、Session state、Memory turn 等）；`Agent` 实现这些协议。
- R2：`AgentRuntimeCoordinator.__init__` 改为接收窄端口而非单个宽 Host；内部
  `self._host.*` 访问改为对应端口。
- R3：`sync_usage_from_observer` 的参数类型更新为 Usage 端口。
- R4：从 coordinator 拆出 `SessionLifecycle`（新类或新模块），拥有 `clear_history`、
  `restore_core_session`、`compact`、`close` 及其专属的 recorder 管理逻辑。
- R5：`reset_core_observers` 和 `reset_session_counters` 被 SessionLifecycle 和
  coordinator（`__init__` / `chat`）共用；采用持有 coordinator 引用或提取为共享方法的
  方式，不复制逻辑。
- R6：`Agent` 的 `clear_history()`、`restore_core_session()`、`compact()`、`close()`
  委托从 coordinator 改为 SessionLifecycle（或 coordinator 转发）。
- R7：保持 `AgentRuntimeHost` 的所有消费者行为不变：`chat()`、`run()`、`run_once()`
  时序、MCP 初始化、Memory overlay、JSONL append/replay、Plan 模式恢复、关闭顺序。
- R8：不引入 Service Locator 或全局注册表；端口通过构造函数注入。
- R9：`Agent.__init__` 可折叠 `AgentDependencies` dataclass 收敛构造参数（可选，如果
  能简化端口注入）。

## Acceptance Criteria

- [ ] AC1：`AgentRuntimeHost` 不再作为 coordinator 的唯一入口；coordinator 构造函数
  接收 3-4 个窄端口。
- [ ] AC2：coordinator 中 `self._host.*` 访问被替换为对应端口访问；不存在一个端口
  暴露全部 27 字段的情况。
- [ ] AC3：`SessionLifecycle` 独立拥有 clear/restore/compact/close，且不复制
  reset_core_observers / reset_session_counters 逻辑。
- [ ] AC4：全量测试、compileall、import-linter、架构测试通过；无新增 ruff/mypy/format
  基线回归。
- [ ] AC5：`agent_runtime.py` 物理行数显著下降（SessionLifecycle 拆出约 200 行）。
- [ ] AC6：Agent 的公共 API（`chat` / `run` / `run_once` / `clear_history` /
  `restore_core_session` / `compact` / `close` / `abort`）行为不变。

## Out of Scope

- 继续拆分 coordinator 中的 ContextLifecycle、ExecutionRunner 或 ObserverRegistry。
- 修改 Core Harness、Provider 协议、ToolRuntime 中间件、JSONL schema、Memory 语义。
- 修改 CLI/TUI UX 或产品行为。
- 清理历史 ruff/format/mypy 基线。

## Notes

- 前置任务：`08-06-cleanup-agent-coordinator-compat`（PR #17）已删除兼容层，本任务
  在干净的单层委托基础上拆端口。
- 如果窄端口拆分导致大量构造参数，可用 `AgentDependencies` dataclass 打包端口。
