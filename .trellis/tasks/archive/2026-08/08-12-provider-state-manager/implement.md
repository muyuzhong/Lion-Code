# Provider 配置与 Thinking 生命周期实施计划

## Ordered checklist

1. **基线与契约**
   - 记录当前 master/dirty worktree；只修改本任务涉及的生产代码、测试、规范和 task
     artifacts，保留已有 `.claude` / `.codex` / `.trellis` WIP。
   - 读取并遵守 backend runtime-boundaries、directory-structure、quality 规范。
2. **ProviderManager 核心**
   - 新建 `lion_code/provider_manager.py`，实现 `ProviderState`、冻结 `ProviderView`、
     四个窄 Protocol 和 `ProviderManager` commands。
   - 迁移配置解析、factory 调用、Thinking normalize/coerce、replacement transaction、
     recorder scheduling 和 old-provider close；不 import `Agent`。
   - 保留 `provider_factory` Callable 的动态 `lion_code.agent.create_provider` patch seam。
3. **组合根与 facade**
   - 在 `Agent` 组合 Manager、初始 State 和窄适配器；删除 `AgentLifecycle` 实例、
     `AgentLifecycleHost` 以及 Provider mutable mirrors。
   - 将 public model/provider/config/thinking API、`_build_core_provider`（若仍被内部调用）
     和 child credential projection 改为 Manager/View 委托。
   - 保持唯一 `AgentRuntimeCoordinator` / `LionAgentRuntime` / canonical history。
4. **Runtime / restore 接线**
   - 让现有 coordinator 提供窄 runtime/context control 实现，并把 Manager 作为
     `SessionLifecycle` 的显式 restore command 依赖。
   - 将 Session restore 的 model/thinking 私有字段写入替换为
     `ProviderManager.restore_configuration()`，不新增重复 Session entry。
   - 不修改 Memory Host、Capability PromptLayer、AgentBuilder 或其他非 Provider Host 的
     ownership 设计。
5. **回归与架构测试**
   - 更新原有 lifecycle integration assertions；新增 Manager unit tests 和用户要求的五类
     architecture guards。
   - 覆盖 model-only、协议/credential/base/Thinking replacement、失败回滚、busy、history、
     compactor、query、cache、async close、restore、persistence 和 patch seam。
6. **规范同步**
   - 更新 `.trellis/spec/backend/runtime-boundaries.md` 与 `directory-structure.md`，只记录
     实际落地的 ProviderState/Manager/View/port 契约和删除的 AgentLifecycle，不写计划性
     能力。
   - 完成 Trellis spec review，必要时更新 PRD acceptance 状态。

## Validation matrix

```powershell
python -m pytest -q tests/providers tests/integration/test_agent_core_runtime.py tests/application/test_coding_session_ports.py tests/memory_runtime/test_core_integration.py
python -m pytest -q tests/architecture/test_runtime_boundaries.py
python -m compileall -q lion_code tests
ruff check lion_code tests
ruff format --check lion_code tests
lint-imports --no-cache
git diff --check
python ./.trellis/scripts/task.py validate .trellis/tasks/08-12-provider-state-manager
python -m pytest -q
```

全量 mypy/Ruff 若受已有 baseline 影响，单独报告 baseline 与本任务新增诊断；不得把历史
诊断误报为本次回归。最终 quality check 必须覆盖 affected package 的完整测试矩阵。

## Risk / rollback points

- **Factory seam**：若 patch `lion_code.agent.create_provider` 不再覆盖 Manager，立即停止并
  修正 factory Callable wiring；不改测试到新模块路径。
- **Atomicity**：若 replacement 构建异常后旧 State/Runtime/服务有变化，回滚 Manager commit
  逻辑，先恢复 build-before-mutate 顺序。
- **Single runtime**：若 restore/swap 创建第二个 `LionAgentRuntime`、Harness 或 writer，
  回退接线，只允许既有 runtime `replace_provider`。
- **Restore**：若 JSONL model/thinking 不能恢复或重复追加 entry，回滚 SessionLifecycle
  调用边界并保留已有 recorder replay。
- **Scope**：若改动扩散到 Memory Host、Capability PromptLayer、AgentBuilder 或其他 Host，
  停止并移除越界修改。

## Pre-start gate

- `prd.md`、`design.md`、`implement.md` 已完成且无 blocking open question。
- `implement.jsonl` / `check.jsonl` 已填入实际 spec context。
- 用户批准最终 planning summary 后，才运行 `task.py start` 并进入实现阶段。
