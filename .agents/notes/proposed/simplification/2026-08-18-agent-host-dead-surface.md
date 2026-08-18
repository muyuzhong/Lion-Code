# Agent Note: 清理内部 Agent 宿主与 AgentComposition 的死面（镜像字段、无引用方法、别名堆叠、死 __setattr__）

- Status: proposed
- 日期: 2026-08-18
- 范围: `lion_code/agent.py`、`lion_code/meta_agent.py`、`lion_code/composition/agent_builder.py`、`tests/integration/test_agent_core_runtime.py`、`tests/integration/test_meta_agent.py`、`tests/tooling/test_agent_runtime.py`、`tests/architecture/test_runtime_boundaries.py`

## Problem

PR10/PR11 的组合根把对象图构造收拢到 `build_agent_composition` 的一次性语义后，
内部宿主 `Agent` 仍在 `__init__` 里把整张图镜像到 `self`（`agent.py:217-239`），
并保留了一批没有调用者的方法/别名/拦截器：

1. **8 个镜像属性 + 8 个零读者组合字段**：`agent.py:217-239` 存储
   `_identity_port`/`_session_port`/`_permission_controller`/`_read_file_state`/
   `_pre_tool_use_hooks`/`_skill_runtime`/`_permission_policy`/`_result_store`；
   每个名字 `rg` 全仓只有赋值点（或只被同样是死面的属性读取，见 #2）。
   `AgentComposition` 上对应的 `execution`/`permission_controller`/`read_file_state`/
   `pre_tool_use_hooks`/`result_store`/`context_manager`/`identity_port`/`session_port`
   字段（`agent_builder.py:99-135`）同样零读取——生产与测试都只读
   `runtime_coordinator`/`tool_registry`/`tool_runtime`/`capability_*`/`plan`/
   `subagent_*`/`permission_policy` 等字段。对象本身仍在构造并被注入 runtime，
   只是「复制一份暴露在宿主上」这段没有消费者。
2. **9 个无引用/仅测试引用方法**（`agent.py`）：`_resolve_thinking_mode`（:245）、
   `session_start_time`（:352）、`_emit_subagent_status`（:441）、`_create_provider`
   （:496）、`_build_core_provider`（:492）、`_terminal_output` 属性（:305-313）、
   `_create_terminal_renderer`（:338）——全仓零引用；`use_openai`（:249）只被
   `tests/integration/test_agent_core_runtime.py:1046` 引用；`_is_snippable_tool`
   （:592-597）只被 `tests/tooling/test_agent_runtime.py:188-191` 引用，且是
   `agent_builder.py:723-728` 同逻辑的精确复制（生产只走 builder 那份，
   `agent_builder.py:651` 传给 `ContextManager`）。
3. **别名堆叠**：`MetaAgent.conversation`（`meta_agent.py:95-96`）是 `messages`
   （:90-92）的纯别名，零引用，只被 `tests/integration/test_meta_agent.py:369`
   钉在精确表面清单里；`Agent.provider_config`/`configure_provider`
   （`agent.py:400-404`）重定义成 `get_api_config`/`configure_api`（:470-490）
   的委托，而后者又委托 `provider_manager`——与继承自 `MetaAgent` 的同名实现
   （`meta_agent.py:140-158`）是同一件事的两层包装，应用程序只按
   `CodingSessionBackend` 协议名字调用（`application/ports.py:91,93`）。
4. **死 `__setattr__` 拦截**（`agent.py:103-113`）：拦截对 `_emit_notice` 的赋值并改道
   `NoticeController.set_notice_fn`；`rg "_emit_notice ="` 与 `setattr(..., "_emit_notice")`
   全仓零命中，通知走 `set_notice_fn`（`tui/app.py:791,808` → `application/session.py:307-313`
   → `agent.py:425-431`）。

例外说明：`_create_provider`/`_build_core_provider` 被 `MAINTENANCE.md`（三阶段-5 节）
记录为「FakeProvider patch 锚点」兼容委托——但今天连测试都不 patch 它们
（`rg "_agent_provider_factory" tests` 零命中；真正活着的模块级 seam 是
`agent.py:59-62` 的 `_agent_provider_factory`，经 `agent.py:181` 注入，
本提案保留它）。

## Proposal

1. 删除 `agent.py:217-239` 中 8 个镜像属性；删除 `AgentComposition` 上对应的 8 个
   零读者字段及 `agent_builder.py:278-307` 的赋值（被注入 runtime 的对象继续构造）。
2. 删除 #2 的 9 个方法与 2 个仅测试引用用例（`test_agent_core_runtime.py:1046`、
   `test_agent_runtime.py:188-191`）；`_is_snippable_tool` 逻辑只保留 builder 一份。
3. 删除 `MetaAgent.conversation`；`provider_config`/`configure_provider` 只保留一层
   （建议保留 `MetaAgent` 的继承实现，删除 `Agent` 的 `provider_config`/
   `configure_provider`/`get_api_config`/`configure_api` 并改 `test_agent_core_runtime.py:1064`
   的 `configure_api` 调用到 `configure_provider`——或反向，任选一侧保持协议名可用）。
4. 删除 `Agent.__setattr__` 覆写；`_emit_notice` 回到普通方法。
5. 同步 `tests/architecture/test_runtime_boundaries.py` 的字段断言（:1163 涉及
   `session_start_time` 的缺席断言改为直接删除该断言项/调整期望）、
   `tests/integration/test_meta_agent.py:369` 的表面清单。

## Why not keep it

最强的反方：#2 里两个方法被 `MAINTENANCE.md` 明确记录为兼容委托/#1 的组合字段
可能被未来测试直接读取。但按 `AGENTS.md` 原则 1（不保留向后兼容，过时直接删），
「有文档记录的委托」不是「有消费者的委托」；今天的全仓引用就是证据，连测试都不再
patch 它们。镜像字段的替代消费者完全可以经 `composition.runtime_coordinator.*`/
`composition.context_manager` 到达，`AgentComposition` 一次性语义正是要终结
「宿主背负整张图」的模式——PR11 后的残留正是本提案要清的尾。

## Acceptance criteria

- `rg -n "_identity_port|_session_port|_permission_controller|_read_file_state|_result_store|_resolve_thinking_mode|session_start_time|_emit_subagent_status|_build_core_provider|_create_provider|conversation" lion_code` 零命中（保留 `_agent_provider_factory` 与 builder 版 `_is_snippable_tool`）。
- 生产路径不变：CLI/REPL/TUI 全命令回归（`/model`、`/thinking`、`/cost`、`/clear`、
  `/resume` 走 `Agent` 的路径）通过 `tests/integration/test_application_coding_session.py`、
  `tests/tui/`；全量可跑 unittest 通过。
- 只改 docs/notes 之外必须同步的架构测试期望值；`git diff --check` 干净。

## Risks

- `Agent` 是内部宿主（非包根公共 API，`runtime-boundaries.md` 明确其非公共），删
  方法不构成公共 API 变更；仅 `MetaAgent` 层的方法删除对 embedder 可见，其中
  `conversation` 零引用，`provider_config` 一对被保留一层，风险低。
- `_create_provider`/`_build_core_provider` 若未来要恢复 FakeProvider patch 锚点，
  成本是各 3 行委托——与今天的删除对称。