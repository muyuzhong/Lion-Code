# PR0 架构门禁 — Implement

## 目标

在 `tests/architecture/` 增加四层边界门禁（Kernel/Harness/Capability/Supervisor），使边界由代码验证。基于 boundary-audit 的归属结论锁定。

## 前置

- 等待 08-14-pr0-boundary-audit 产出归属清单（Kernel 归属模块集合、Harness 归属模块集合等）。本 child 引用其结论。
- 若 audit 发现 `core/` 有违规 import，本 child 需在修正后锁定（或记录为后续 PR 入口）。

## 步骤

- [ ] **扩展 `_boundaries.py`**：
  - Kernel 不依赖上层：`source_package="lion_code.core"`，forbidden 扩为 Harness/Capability/Supervisor 全套模块。
  - Capability 不依赖 Agent 引擎（保留）+ 不依赖 Supervisor。
  - Supervisor 不依赖 Agent 私有对象（新增契约）。
  - 同步 `pyproject.toml` import-linter。
- [ ] **新增 `tests/architecture/test_kernel_isolation.py`**（"不是 Kernel" AST 门禁）：
  - 扫描 Kernel 归属模块，断言无 import/引用 `<relevant-memory>`、PlanRuntime、McpCapability、SubagentFactory、Autonomy/Dream/Learning 符号。
- [ ] **zero-extension 合法门禁**：零工具/零能力装配合法（与 test_composition_root 配合）。
- [ ] **Supervisor 订阅契约**（与 event-stream child 共享）：AST 断言 Supervisor 只经 `core.events`/`core.provider_events` 公开类型订阅，不触 `Agent._xxx`。
- [ ] **一致性**：更新 `test_import_linter_config_matches_boundaries` 相关期望（如契约数变化）；更新 spec `runtime-boundaries.md` §6 Executable Enforcement。
- [ ] 跑验收（design §5）：`lint-imports --no-cache`、`tests/architecture`、相关集成测试、全量。
- [ ] 提交（commit without asking）。

## 评审门

- `lint-imports --no-cache` 通过；`test_import_linter_config_matches_boundaries` 通过。
- 四层契约出现在 `_boundaries.py` + pyproject。
- 无 R5 禁止项。
- 全量测试通过；现有 gate 测试（runtime_boundaries/application_ports/tool_routing/composition_root）通过。
