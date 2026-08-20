# Implement: PR3 Runtime Ownership + Provider Dependency DAG

按顺序执行；每步之后 `python -m py_compile` + 定向测试。

## 步骤

1. `runtime/provider.py`：`ProviderManager` → `ProviderController`；
   提出模块级 `build_provider_for_state(factory, state, level)`；
   `ProviderRuntimePort` 增加 `retire_provider`；删除注入的 `schedule_background_operation`
   （Provider 关闭改经 conversation.retire_provider）；`recorder` 端口改名
   `ConfigurationRecorder.record_configuration_change` 语义不变（由 SessionRuntime 实现）。
2. `runtime/conversation.py`：新建 `ConversationRuntime`（自 LionAgentRuntime 迁移，
   增加 run 捕获状态 `_output_buffer/_captured_assistant_text`、
   `retire_provider` + `_background_tasks` + `flush_background_operations`）。
3. `runtime/context.py`：新建 `ContextRuntime`（ContextManager/Compactor/Limits 缓存/
   effective_window/compaction 状态/压缩任务跟踪/prepare_context）。
4. `runtime/session.py`：新建 `SessionRuntime` + `SessionRestoreState`
   （session identity/repository/recorder/能力生命周期/配置 Entry 写任务集/record_configuration_change）。
5. `runtime/agent.py`：重写为 `AgentRuntime`（编排 ensure_ready/compact/chat/run/run_once/
   restore/new_session/close/abort/reset_observers/before_core_tool_calls）+ `AgentRunResult`
   + 瘦 `RuntimeIdentityHost` 协议。删除 LionAgentRuntime/AgentRuntimeCoordinator/SessionLifecycle
   （session_lifecycle.py 文件删除）。
6. `composition/ports.py`：删除 Deferred×3、SessionRecorderConfigurationRecorder、
   SessionStatePort；瘦身 RuntimeIdentityPort。
7. `composition/agent_builder.py`：新构建顺序（context→conversation→session→agent→controller）
   + 分层 AgentComposition（RuntimeComposition/CapabilityComposition/ToolingComposition/
   InteractionComposition）；`composition/__init__.py` 导出更新。
8. `meta_agent.py` / `agent.py`：facade 重接线；`MetaAgent.restore_core_session` 编排
   load→restore_configuration→agent_runtime.restore；`new_session` 读 controller.view 传参。
9. 架构测试 `tests/architecture/test_runtime_ownership.py`（10 项断言）；
   更新 test_runtime_boundaries / test_provider_manager_boundaries 的期望值。
10. 更新行为测试：tests/test_provider_manager.py、tests/runtime/test_agent_runtime.py、
    tests/integration/test_agent_core_runtime.py、test_composition_root/bare/profiles/
    profile_config_bindings、test_kernel_isolation、test_meta_agent、
    test_application_coding_session、tooling 内部测试等。

## 验证命令

```bash
python -m py_compile lion_code/runtime/*.py lion_code/composition/*.py lion_code/meta_agent.py lion_code/agent.py
PYTHONPATH=tests python3 -m unittest discover tests -p "test_*.py"
python -m ruff check lion_code tests scripts
python scripts/check_quality_baseline.py ...（参照 .github/workflows/ci.yml）
```

## 回滚点

整体一个 commit；回滚即 revert 单个 commit。行为不变量：canonical event stream、
JSONL entry 顺序、observer 装配顺序（Usage → Session → Renderer → capture）、
chat 前 ensure_ready 顺序（flush → resolve limits → recorder initialize）。
