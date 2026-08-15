# PR6 MetaAgent Bare Extraction — Implement

## 1. Prepare branch and baseline

- [x] 从已核验的 `master@58564ce` 创建 `muyuzhong/pr6-meta-agent-bare-extraction`，不清理或暂存用户已有工作树改动。
- [x] 跑 PR5 bare composition、Kernel event、ProviderManager 的 focused baseline，记录既有结果。

## 2. Finish bare ownership deletion

- [x] 从 `ProviderManager` 删除 Memory import/protocol/constructor/state/transaction 更新。
- [x] 删除 composition Memory sink adapter/deferred wiring，更新 ProviderManager tests 与架构门禁。
- [x] 将 Feature-specific status/notice/tool-environment helper 改为 capability-gated；Full Product 分支加明确非空断言。
- [x] 增加 direct `ModelProvider` dependency，使 injected provider 是真实 ready state。

## 3. Add MetaAgent facade

- [x] 新增 `lion_code/meta_agent.py` 的 `MetaAgent` 与 `build_meta_agent()`；显式创建 caller-owned tool registry，默认零工具、neutral prompt、empty capability set。
- [x] 只保留 generic runtime/session/provider/usage facade 方法与属性，不保留 composition 或 Feature 字段。
- [x] 从 `lion_code` 公共导出 builder/facade；不更改 Full Product `Agent` 默认行为边界之外的 API。

## 4. Complete Event Stream emission

- [x] 为 `AgentHarness` / `LionAgentRuntime` 增加最小 public emit 委托。
- [x] 在 threshold/manual/overflow compaction 的真实执行点发射 started/completed；取消发 aborted completed。
- [x] 更新 PR0 event contract spec/test，使“声明”变为“真实发射”。

## 5. Add acceptance tests

- [x] 新增 zero-extension + zero-tool smoke test。
- [x] 新增显式 coding tools 的真实 tool-call integration test。
- [x] 新增最强 constructor monkeypatch 全流程负向测试。
- [x] 新增 MetaAgent public surface、default no-coding-tool、bare generic path architecture gate。
- [x] 覆盖 session save/new/restore、compaction events、cancellation events、usage/budget、close。
- [x] 更新 `tests/OWNERSHIP.md`。

## 6. Verify and review

- [x] Focused: `python -m pytest -q tests/architecture/test_bare_composition.py tests/core/test_event_contract.py tests/test_provider_manager.py tests/integration/test_meta_agent.py`。
- [x] Full: `python -m pytest -q`。
- [x] `python -m compileall -q lion_code tests scripts`。
- [x] `lint-imports --no-cache`。
- [x] 按仓库脚本执行 Ruff/mypy/radon/vulture/coverage baseline gates；只更新由 PR6 行号/新增代码引起的基线。
- [x] `git diff --check`，核对 scoped files 与无新依赖。
- [x] 使用 `trellis-check` sub-agent 做独立检查并修正真实问题。

## 7. Spec, commit and handoff

- [x] 更新 `.trellis/spec/backend/four-layer-ownership.md`：PR2 真实状态、MetaAgent contract、compaction emission。
- [x] Trellis validate；仅 stage PR6 文件，中文提交描述。
- [x] 归档任务；若用户要求发布，再 push 并创建职责单一的 PR6。

## Rollback points

- ProviderManager Memory deletion 可独立回滚，但不得以兼容层替代。
- MetaAgent facade/Event emission 与 Full Product Feature re-home 无耦合；PR6 整体回滚恢复 PR5。
