# PR0 边界审计与测试重新分类 — Implement

## 目标

产出 `tests/OWNERSHIP.md` 归属清单 + 更新 spec 四层归属文档。不搬迁、不删测试、不改行为。

## 步骤

- [ ] **核对测试清单**：确认 108 个测试文件/目录全量覆盖（含 fakes/fixtures），无遗漏。
- [ ] **写 `tests/OWNERSHIP.md`**：frontmatter（schema + layers 枚举）+ 归属表（目录级/文件级，mixed 按文件）。标注误导名（`tests/runtime/`、`tests/session_runtime/`、`test_agent_core_runtime.py`）。
- [ ] **写 spec 四层归属文档**：`.trellis/spec/backend/four-layer-ownership.md`（或并入现有文档，见 design §4）：四层定义 + 生产模块映射 + 测试映射 + Capability 归属声明 + "不是 Kernel" 清单 + 交叉引用。
- [ ] **修正 spec 措辞**：在 runtime-boundaries.md / 相关 spec 中，把 `<relevant-memory>`、Plan reset、MCP、SubAgent 从 "Core Runtime 必须行为" 措辞改为 Capability 归属（若存在此类措辞）。
- [ ] **可选**：写一个最小校验脚本或测试，断言 `tests/OWNERSHIP.md` 路径存在 + layer 枚举合法（若归入本 child；否则留给 gates child）。
- [ ] **记录不一致点**：审计发现的"原方案 vs 真实代码"不一致，汇总到本 child 的 notes 或直接供父任务最终总结。
- [ ] **回归**：`python -m pytest -q` 全过。
- [ ] 提交（commit without asking）。

## 评审门

- 归属清单覆盖全部测试，层归属与审计结论一致。
- `tests/runtime/`、`tests/session_runtime/`、`test_agent_core_runtime.py` 误导名已修正。
- `<relevant-memory>`、Plan reset、MCP、SubAgent 归 capability。
- 未删除/移动测试；全量测试通过。
- spec 与现有文档（runtime-boundaries、capability-spi）一致。
