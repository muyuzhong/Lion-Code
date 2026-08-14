# PR0 边界审计与测试重新分类 — Design

## 1. 目标

产出测试→四层归属清单，修正 "core runtime" 误标签，更新 spec。不搬迁、不删测试。

## 2. 归属清单格式（机器可读 + 人类可读）

### 2.1 单一权威清单：`tests/OWNERSHIP.md`

`tests/OWNERSHIP.md` 是权威归属表，格式为 markdown 表 + 顶层 YAML frontmatter（供门禁读取）：

```markdown
---
schema: test-ownership/v1
layers:
  kernel: "Kernel 契约测试"
  harness: "Harness 契约测试"
  capability: "Capability 契约测试"
  supervisor: "Supervisor 契约测试"
  product: "Product integration"
  eval: "Eval/CI infra"
  mixed: "跨层（见备注）"
---
# Test Ownership

| 测试文件/目录 | Layer | 备注 |
|---|---|---|
| tests/core/ | kernel | 纯 Kernel |
| tests/runtime/ | harness | **名字误导**：测 agent_runtime.py(coordinator)+observers |
| tests/session_runtime/ | harness | JSONL 持久化 |
| tests/integration/test_agent_core_runtime.py | mixed | Kernel+Harness+Capability[Plan/SubAgent] |
| tests/memory_runtime/test_injector.py | capability | `<relevant-memory>` |
| tests/test_plan_runtime.py | capability | Plan reset |
| ... | ... | ... |
```

- **不用 pytest marker 逐个标注**（100+ 文件改动量大，属于"大规模"）；用单一清单 + 文档重定义归属。
- frontmatter `schema` 版本化；gates child 可写校验测试：清单内路径存在、layer 枚举合法、无重复。

### 2.2 目录级 + 文件级混合粒度

- 目录内归属一致的：目录一行。
- 目录内 mixed 的：按文件列（如 `tests/tooling/`、`tests/integration/`）。

## 3. 修正 "core runtime" 误标签

### 3.1 清单中标注误导名

- `tests/runtime/` → `harness`，备注"名字误导：非 Kernel core runtime"。
- `tests/session_runtime/` → `harness`。
- `tests/integration/test_agent_core_runtime.py` → `mixed`，备注"含 Capability/Supervisor 行为，非纯 Kernel"。

### 3.2 修正 spec 语言

在 spec 四层归属文档中明确：

- Kernel 契约测试 = `tests/core/` + `tests/context/` + `tests/providers/` + `test_usage.py` + `test_agent_run.py`（断言层）+ `test_model_query.py`。
- `tests/runtime/`、`tests/session_runtime/` 属 **Harness**，不是 Kernel。
- `<relevant-memory>`（`MemoryContextInjector`）、Plan reset、MCP、SubAgent 属 **Capability**，其测试归 capability。
- "core runtime 必须行为"这个措辞废弃，替换为"Kernel 不变量"。

### 3.3 原方案 vs 真实代码不一致点（记录供父总结）

| 原方案假设 | 真实代码 | 影响 |
|---|---|---|
| "core runtime 测试"是核心 | `tests/core/` 纯 Kernel；但 `tests/runtime/`/`tests/session_runtime/`/`test_agent_core_runtime.py` 是 Harness/Mixed | 归属清单修正 |
| `<relevant-memory>` 是 runtime 行为 | 是 Memory Capability（`memory_runtime/injector.py`） | 归 capability |
| MCP/SubAgent 是核心 | 是 Capability | 归 capability |
| Plan reset 是 core | 是 Plan Capability | 归 capability |

## 4. spec 更新：四层归属文档

新增 `.trellis/spec/backend/four-layer-ownership.md`（或并入 runtime-boundaries.md 的章节，取决于现有文档结构；倾向独立文档避免 runtime-boundaries 过长）。内容：

1. 四层定义（引用父 design §2 的 Contract）。
2. 生产模块 → 层映射表（已核实）。
3. 测试目录/文件 → 层映射表（来自 `tests/OWNERSHIP.md`）。
4. `<relevant-memory>`/Plan reset/MCP/SubAgent 的归属声明（Capability）。
5. "不是 Kernel" 的边界清单。
6. 与 runtime-boundaries.md、capability-spi.md 的交叉引用。

## 5. 边界

- 不修改生产代码（本 child 只产出清单与文档；如审计发现 `core/` 有违规 import，记录到清单/总结，交由 gates child 或后续 PR）。
- 不移动/删除任何测试文件。
- 不改测试行为。

## 6. 验收验证命令

- 清单路径全部存在：门禁校验（gates child）或本 child 简单校验脚本。
- `python -m pytest -q`（不改行为，应全通过）。
