# 三阶段-2:提取 session_memory_coordinator

> 本任务最初为创建预留，现已获得执行授权。它是三阶段路线图中
> `autonomy_runtime` 之后的下一职责，实施在独立分支
> `feat/phase3-session-memory-coordinator` 上，并以父任务
> `07-30-project-session-memory` 的已实现边界为约束。

## Goal

把 SessionMemory(项目短期状态)、dream、handoff 与 memory overlays 的**状态所有权与协调**从 `agent.py` 迁入新模块 `session_memory_coordinator.py`,使「新增/改 Memory 功能」不再需要同时理解 Goal、Provider 切换与 TUI 输出。延续三阶段约束:一次一职责、先测试后移动、不改产品行为、Agent 对外 API 不变、Core 消息历史唯一、不引入 Service Locator。

## 实施前现状

SessionMemory/Memory 相关状态与方法散落在 agent.py,与 Core 运行时、Provider、chat 主路径纠缠:
- `dream` 调用 Provider 做隔离蒸馏，`_refresh_memory_context_after_dream` 回调
  `MemoryCoordinator`。
- `_prepare_turn_memory_snapshot` / `_build_turn_memory_overlays` 被 chat 主路径与
  `_prepare_core_context` 消费。
- `_update_session_memory_after_turn` / `_extract_session_memory_semantics` 在每轮后
  从工具证据更新短期状态。

## 迁入 SessionMemoryCoordinator 的状态(agent.py __init__)
`_session_memory_repository`、`_session_memory`、`_session_memory_error`、`_reported_session_memory_error`、`_project_identity`、`_project_memory_overlays`、`_turn_memory_overlays`、`_memory_coordinator`、`_memory_injector`、`_last_memory_injection`

## 迁入的方法(agent.py)
- 展示/编辑:`show_session_memory`(522)、`show_active_task`(527)、`switch_session_task`(532)、`finish_session_task`(539)、`create_session_handoff`(556)、`_editable_session_memory`(566)、`_save_session_memory`(578)
- 加载/overlay:`_reload_project_memory`(588)、`_build_turn_memory_overlays`(606)、`_prepare_turn_memory_snapshot`(622)、`_build_core_memory_query_service`(632)、`_reload_session_memory`(1988)、`_report_session_memory_error`(1998)
- 轮后更新:`_update_session_memory_after_turn`(2005)、`_extract_session_memory_semantics`(2036)
- dream:`dream`(1512)、`_refresh_memory_context_after_dream`(1536)

## 模式(同 autonomy_runtime)
1. `SessionMemoryHost` 窄协议：host 提供 `_core_runtime`、项目指令加载、通知、
   Dream 所需的工具/Provider 配置和动态系统提示刷新；coordinator 不持 Provider/TUI。
2. `SessionMemoryCoordinator` 拥有上述状态 + 方法,经 host 回调。
3. Agent 保留薄委托(public:`show_session_memory`/`show_active_task`/`switch_session_task`/`finish_session_task`/`create_session_handoff`/`dream`)+ 状态属性委托(被 chat/_prepare_core_context 等读取的字段)。
4. 边界:coordinator **拥有** overlays 与 MemoryCoordinator;`_prepare_core_context`(留 agent.py/agent_runtime)**消费** overlays。dream 经 host 拿 provider(或 `_build_core_memory_query_service` 留 agent.py 作共享,coordinator 调用)。

## 先测试(迁移前补特征测试)
- dream:`test_dream.py` 已有(测 `_update_memory_index` 等);补 `dream()` 与 `_refresh_memory_context_after_dream` 的协调测试(stub provider/MemoryCoordinator.invalidate)。
- session_memory:`test_session_memory.py` 已有;确认 `show/switch/finish/handoff` 经 Agent 公共 API 的覆盖,缺口补齐。
- `_update_session_memory_after_turn`/`_extract_session_memory_semantics`:核查覆盖,无则补(stub 工具证据 -> 断言 SessionMemory 字段更新)。

## 步骤
1. 补特征测试 -> 绿(针对当前 Agent)。
2. 新建 `lion_code/session_memory_coordinator.py`:`SessionMemoryHost` Protocol + `SessionMemoryCoordinator`。
3. agent.py:`__init__` 移状态、加 `self._session_memory_coord = SessionMemoryCoordinator(self)`;方法改薄委托;加状态属性委托。
4. 跑 dream/session_memory/integration + 全量 -> 绿。
5. ruff/mypy/format 不超基线(218/146/105);agent.py 应再降 ~300 行(-> ~1850)。
6. 提交;更新 MAINTENANCE 瘦身账 + baseline 文档测试数。

## 风险
- dream 调 Provider:需明确 host 提供 provider 还是 `_build_core_memory_query_service` 留 agent.py(coordinator 调用)。后者更稳(与 autonomy 的 side-query 同模式)。
- `_prepare_core_context` 消费 `_turn_memory_overlays`/`_last_memory_injection`:coordinator 拥有这些字段,agent.py 经属性委托读取--确保 _prepare_core_context 迁移前仍能读到。
- `_memory_coordinator.set_query_service` 在 __init__ 末尾被调(依赖 provider):coordinator 构造时 host._core_runtime 可能未就绪--延迟到 provider 就绪后(同 autonomy 运行时才用的模式)。
- 多处读取 `_session_memory`/`_session_memory_error`(chat、restore_core_session):需属性委托,逐处核查(grep `_session_memory` 全仓)。

## 完成结果
- [x] `agent.py` 从 1,890 行降至 1,801 行；公共
  `show_*/switch_*/finish_*/create_session_handoff/dream` 签名不变。
- [x] 全量测试 `547 passed, 6 skipped, 6 subtests passed`；ruff 218 / format
  146 / mypy 102，未引入新的静态错误。
- [x] `_prepare_core_context` 继续通过 Agent 兼容属性读取固定 Overlay；Dream、
  Session Memory 生命周期和每轮确定性工具证据行为保持不变。
- [x] 无全局 Service Locator；coordinator 仅经 `SessionMemoryHost` 窄协议回调
  Agent。
