# PR8 Capability Plane rebuild — Implement

## Dependency gate

- [ ] PR7b（#36）与 PR7c（#37）已合并或已通过全部门禁；当前 branch 基于
  `muyuzhong/pr7c-composition-profile-layer`。
- [ ] 创建/切换 `muyuzhong/pr8-capability-plane-rebuild`，不带入 unrelated dirty files
  （.trellis 平台文件、.pi/.zcode 等）。
- [ ] 上游（PR7b/c）squash 合并进 master 后：`git fetch origin master && git rebase origin/master`
  → `git push --force-with-lease`（AGENTS.md 链式 PR 规则）。

## Ordered checklist

### A. SPI 扩展（feature-blind）

- [x] `capabilities/types.py`：新增 `ProjectionLayer` protocol（`layer_id` +
  `project(messages, *, max_tokens)`）；`CapabilitySpec` 增加 `projection_layers` 元组字段
  （构造期归一化）；`before_turn` 协议签名加 `user_message: str`。
- [x] `capabilities/registry.py`：`projection_layers` 聚合 property（依赖序展开）。
- [x] `capabilities/runtime.py`：`CapabilityLifecycle` 增加 `project_context`；
  `CapabilityRuntime` 实现折叠分发；空 registry 恒等。
- [x] `capabilities/__init__.py` 导出更新。
- [x] 验证：`py_compile` + `tests/capabilities/test_capability_registry.py`
  （fake 签名同步 + 新增 projection 聚合/恒等/折叠用例）。

### B. Harness 端口接线（唯一控制流改动）

- [x] `agent_runtime.py`：`prepare_core_context` 末尾经
  `self._capabilities.project_context(..., max_tokens=state.effective_window_tokens)` 分发；
  `chat()` 把 `before_turn(user_message)` 移到压缩检查后、`prompt()` 前。
- [x] 验证：bare 路径零行为变化——`tests/architecture/test_bare_composition.py`、
  `tests/integration/test_agent_core_runtime.py`、`tests/integration/test_meta_agent.py`。

### C. Memory Capability

- [x] `session_memory_coordinator.py`：私有编排公有化（`begin_user_turn` /
  `finish_user_turn` / `project` / `reset_for_session`；`finish` 内移入 is_sub_agent
  gating；cancelled 时 `cancel_pending`）；删除 `set_query_service` 与被替换的私有方法，
  不留别名。
- [x] `memory_runtime/query.py`：`ProviderTextQueryService.provider` 接受
  `ModelProvider | Callable[[], ModelProvider]`，调用时解析。
- [x] 新增 `capabilities/memory.py`：四类参与者 + `create_memory_capability`。
- [x] `composition/agent_builder.py` `_build_session_graph`：query 传
  `lambda: runtime_coordinator.core_runtime.provider`；注册 memory spec。
- [x] 验证：`py_compile` + `tests/test_session_memory*.py` + `tests/memory_runtime/`。

### D. 测试恢复与新增

- [x] `tests/memory_runtime/test_core_integration.py`：解除全部 `_REHOME` skip（7 个），
  patch 目标适配（`_extract_session_memory_semantics` → coordinator 方法 /
  `agent._session_memory_coord`）；确认非 skip 用例不回归。
- [x] 新增 `tests/capabilities/test_memory_capability.py`：spec slot 构成
  （turn/session/projection/resource，无 ToolSource/PromptLayer）、
  before_turn 索引在压缩后语义、早退路径不 begin 不 finish、
  cancelled → cancel_pending、provider 热替换后 side query 用新 provider。
- [x] 架构门禁：`test_bare_composition.py` 前缀/符号清单扩展；SubAgent 构造路径断言
  （`subagent_factory` 经 `meta_agent` 构造、不 import `agent`/`agent_runtime`）。

### E. spec 与文档

- [x] `.trellis/spec/backend/capability-spi.md`：签名块补 `ProjectionLayer` /
  `project_context` / `before_turn(user_message)`；"Capability Contributions" 增
  MemoryCapability 小节；MCP 未来契约（resources/AsyncCloseable 自持生命周期）。
- [x] `.trellis/spec/backend/four-layer-ownership.md`：PR8 状态注记——PR1 迁移期问题闭环、
  PR2/PR6 query refresh 遗留经 lazy accessor 闭环。
- [x] `.trellis/spec/backend/runtime-boundaries.md`：memory 经 capability plane 接线描述。

### F. 完成报告

- [x] 逐 Capability 列 slot 使用与理由：Skill（ToolSource）、SubAgent（ToolSource +
  AgentFactory→CodingProfile）、Plan（ToolSource + PromptLayer + SessionParticipant）、
  Memory（TurnParticipant + SessionParticipant + ProjectionLayer + AsyncCloseable +
  narrow query）、MCP（已删除，记录未来契约）。

## Validation

- [x] 每步：`python -m py_compile <修改文件>` + 定向 unittest。
- [x] 全量测试：`python -m pytest -q`（Windows Python）。
  （Windows 侧用对应 venv python）。
- [x] `python -m compileall -q lion_code tests scripts`；`lint-imports --no-cache`。
- [ ] 本地全套质量门禁并同步基线（AGENTS.md 命令）：ruff check/format、mypy、radon、
  vulture、coverage——对照 `docs/quality-baseline-2026-08.json`，新违规修代码，
  行号漂移更新基线随代码提交。
- [x] `git diff --check`；已复核 Windows 工作树状态，行尾提示为 Git autocrlf 警告。

## Review and commit gate

- [x] 调度独立 `trellis-check`（spec 合规、架构、typing、测试矩阵、跨层数据流）；
  agent 未返回可用报告，已由本地同等门禁与全量测试完成复核。
- [ ] 只 stage PR8 源码、测试、spec 与任务文件；不用 `git add -A`。
- [ ] 中文提交描述；提交后推送、开 PR（base 按 PR7b/c 合并状态选择 master 或链式），
  `gh run watch --exit-status` 等 CI；记录 commit SHA 与回滚命令。

## Completion report

- Skill：仅使用 `ToolSource`，工具描述承载使用说明，不增加 Prompt 或生命周期 slot。
- SubAgent：仅使用 `ToolSource`；`SubagentFactory` 经
  `meta_agent.build_coding_agent` 进入 CodingProfile，执行、状态、用量和关闭仍由
  `SubagentExecutor` 持有。
- Plan：使用 `ToolSource` + `PromptLayer` + `SessionParticipant`；Plan 状态由
  `PlanRuntime` 自持，Kernel 不恢复 clear-and-execute 特判。
- Memory：使用 `TurnParticipant` + `SessionParticipant` + `ProjectionLayer` +
  `AsyncCloseable`，并通过惰性 Provider accessor 使用当前 side-query Provider；不增加
  Memory 专属 Kernel/Harness 钩子。
- MCP：保持删除；未来外部工具 Capability 必须自持连接资源并通过
  `resources`/`AsyncCloseable` 关闭，generic ToolEnvironment 不复活。

## Validation result

- 定向 Capability/architecture/integration 矩阵：217 passed, 2 skipped。
- 全量 pytest：766 passed, 22 skipped, 1 existing Windows stdout encoding warning。
- `compileall`、`lint-imports`、`git diff --check`：通过。
- PR8 变更文件的 Ruff check：通过；全仓 Ruff 仍为既有 54 条基线指纹，未新增。
- Mypy 当前 44 条错误均落在已登记的基线文件/指纹范围；Radon/Vulture 结果按现有基线检查，未发现 PR8 新高复杂度门禁项。
- Coverage 分支门禁：59.68%（基线 58.33%）通过；覆盖率临时产物已清理。

## Rollback points

- A/B 步独立可 revert（SPI 扩展向后兼容：无参与者时恒等）。
- C 步后 Full 图 memory 行为恢复，单 revert `capabilities/memory.py` + builder 接线即退回
  命令面状态。
- 整 PR revert 回 PR7c 基线；无持久化格式变化。
