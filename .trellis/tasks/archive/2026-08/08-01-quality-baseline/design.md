# 质量基线：技术设计

## 1. 决策摘要

| 决策点 | 结论 | 依据（实测） |
|---|---|---|
| CI 阈值策略 | **基线模式**：固定范围子集必须全绿 + 全量违规数作为基线阈值记录，不设硬失败 | `ruff check .` 423 错、`format` 147 文件待排、mypy 103 错——全绿不现实 |
| 类型检查 | **mypy**（已装 2.3.0） | basedpyright 未装；mypy 已可用 |
| ruff 规则范围 | 拆两层：CI 强制层（`E,F,I,RUF` 可自动修复子集）+ 全量层（写入基线文档） | `--select E,F,I` 触发 1153 错（E501 行宽为主），不能全选；默认 423 错含 194 个可自动修复 |
| 覆盖率 | 只报告不设 fail_under（基线模式） | 用户 R3.3 明确 |
| 循环依赖 | import-linter 定义契约层，CI 校验 | ast 粗测 0 循环；import-linter 已装 2.11 |
| vulture | 记录 4 个高置信候选为基线清单 | 实测仅 4 个 |

## 2. 架构契约（import-linter）

按现有目录结构定义依赖边界（匹配仓库实际架构）：

```
lion_code
├── adapters      → core, providers (薄转换层)
├── application   → core, context, tooling
├── core          → (自身 + context) 最底层
├── context       → core
├── memory_runtime → core, context
├── observers     → core, context
├── providers     → core, context
├── session_runtime → core, context
├── tooling       → core, context
├── tui           → application, core, providers, tooling
└── 根模块        → 任意
```

契约：`application` 不依赖 `tui`；`tui` 不依赖 `memory_runtime`；`core` 不依赖任何上层包。基准契约文件 `lint_contracts.py`。

**风险**：真实依赖可能违反该契约（如 tui→providers 是否成立需实测）。implement 阶段先跑 import-linter 探测实际依赖图，若违反则调整契约到与现状一致，把「契约不匹配」也记为基线项。**契约必须反映现状，不追求理想架构**——理想架构是后续精简阶段的事。

## 3. CI 设计

`.github/workflows/ci.yml` 单 workflow，Python 3.12。

**Job 1 `lint`（基线模式，不阻塞）**：
- `ruff check .` → 输出统计 + 写 `docs/quality-baseline` 对比
- `ruff format --check .` → 同上
- `python -m compileall -q lion_code tests`（必须通过）
- `git diff --check`（必须通过）
- import-linter 契约校验（尝试运行；若契约与现状不符，本阶段标记 not passing）
- mypy → 输出错误统计

**Job 2 `test`（必须通过）**：
- `python -m pytest -q`
- coverage 分支覆盖率 → 输出报表（不设 fail_under）

**「不得继续恶化」机制**：
- 阶段一：把全量违规数（ruff 423 / format 147 / mypy 103 / coverage 待测）写入基线文档。
- 阶段二（本任务内可选）：CI 加一步比对——若当前违规数 > 基线，输出 warning 并 fail。因用户要求「先记录基线，执行不得继续恶化」，本任务落地 CI 的**只报告**版本 + 基线文档记录；严格 fail 阈值留待用户确认后加（见 implement 的决策点 D1）。

## 4. 配置方案

**pyproject.toml** 新增：

```toml
[tool.ruff]
target-version = "py312"
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "RUF", "UP", "B", "SIM"]
ignore = [
  "E501",   # 行宽：全项目大量存在，基线模式忽略
  "BLE001", # 宽泛 except：99 处，属现有风格，后续阶段处理
]

[tool.mypy]
python_version = "3.12"
warn_unused_configs = true
ignore_missing_imports = true
check_untyped_defs = true

[tool.pytest.ini_options]
addopts = "-ra"
asyncio_mode = "auto"

[tool.coverage.run]
branch = true
source = ["lion_code"]

[tool.coverage.report]
show_missing = true
skip_covered = true

[tool.radon.cc]
min = "C"

[tool.vulture]
paths = ["lion_code", "tests"]
min_confidence = 70

[tool.importlinter]
root_package = "lion_code"
contract_files = ["lint_contracts.py"]
```

**注意**：`[tool.ruff.lint]` 的 ignore 是基线模式的直接体现——忽略项必须写注释说明原因，后续阶段逐条收紧。

## 5. 待决策点（implement 阶段验证后定）

- **D1**：CI 是否在本任务内就加「违规数 > 基线 → fail」。倾向：加。理由：这是「不得继续恶化」的直接落地，且基线已是当前值，不产生额外负担。但需要用户确认。
- **D2**：ruff ignore 清单具体范围。先按上表，跑一遍确认 CI 子集全绿，再按实际违规调整。
- **D3**：import-linter 契约的最终形态，取决于实测依赖图。
- **D4**：coverage 是否设 fail_under。默认不设（用户 R3.3）。

## 6. 范围外（明确不做）

- 不修改任何 `lion_code/`、`tests/`、`benchmarks/` 的 .py。
- 不做功能改动、不重构。
- 不处理 `docs/tui-migration-audit.md`（git D 状态，非本任务范围）。
- 不设覆盖率高门槛；不追求 ruff/mypy 全绿。
