# 第一阶段：停止扩功能，建立质量基线

## Goal

在**代码精简**整体工作开始前，先停止新增功能，建立可量化、可复现的质量基线，并架设「不得继续恶化」的护栏（CI + 静态工具），为后续按模块的瘦身提供数据依据和回归保护。

本任务只做**纯治理迭代**：测量、记录基线、引入工具链、配置 CI。不做任何功能改动、不做大规模重构。唯一的代码改动是必要的配置文件（pyproject.toml 的 tool 段、CI workflow、基线文档）。

## 核心原则（用户明确要求）

1. **先停止扩功能**——本阶段不新增/修改产品行为。
2. **先记录基线**——不要求全项目严格通过。
3. **执行「不得继续恶化」**——以基线为阈值，CI 只拦截**比基线更差**的情况。
4. **再按模块逐步提高标准**——后续阶段再逐模块收紧。

## Requirements

### R1. 基线数据（本轮必须回答的问题）

对以下指标建立第一条基线并记录到 `docs/quality-baseline-2026-08.md`：

- R1.1 生产代码、测试、Benchmark 分别多少行（文件数 + 行数）。
- R1.2 最大的 20 个文件和最大的 20 个函数（按行数）。
- R1.3 圈复杂度最高的模块与函数（radon 精确值；与 ast 粗代理交叉核对）。
- R1.4 是否存在循环依赖（模块级 import 图；记录工具与结果）。
- R1.5 哪些文件同时具有高复杂度与高提交频率（churn 热点）。
- R1.6 分支覆盖率百分比（coverage.py --branch）。
- R1.7 完整测试耗时、不稳定测试（先跑一次全量，记录耗时；flaky 用 CI 历史/复跑判定）。

基线文档中每条指标必须附**测量命令**，保证可复现。

### R2. 工具链引入（本阶段为基线模式，不强制全绿）

| 工具 | 用途 | 引入方式 |
|---|---|---|
| Ruff | 格式、基础错误、导入、复杂度（C901/PLR091x） | 已装；写入 pyproject [tool.ruff] 配置 |
| basedpyright 或 mypy | 类型检查（二选一） | mypy 已装；写 [tool.mypy] 配置 |
| coverage.py | 分支覆盖率 | 需安装；写入 pytest 配置 |
| radon | 圈复杂度和可维护性指数 | 需安装；用于基线测量命令 |
| vulture | 死代码候选 | 需安装；记录基线候选清单 |
| import-linter | 架构依赖边界 | 需安装；定义架构契约层 |

规则：
- R2.1 工具全部**以基线模式**引入：先记录当前得分，再以基线为阈值设 CI。
- R2.2 每个工具在 pyproject.toml 的 `[tool.*]` 段配置，配置写明忽略项及原因。
- R2.3 工具安装作为 dev 依赖写进 pyproject `[project.optional-dependencies]` 的 `dev` 组。

### R3. CI（GitHub Actions）至少包含

按用户指定顺序，`CI 至少执行`：

1. `ruff check .`
2. `ruff format --check .`
3. `python -m compileall -q lion_code tests`
4. `python -m pytest -q`
5. `git diff --check`

规则：
- R3.1 使用 Python 3.12（与 `requires-python = ">=3.12"` 一致）。
- R3.2 `ruff check .` 与 `ruff format --check .` 本阶段**允许已存在违规**：配置基线阈值（选：立即全绿 或 仅拦截新增）——由 implement 阶段验证当前违规数后决策，见 design.md。
- R3.3 coverage 作为附加 job 或附加步骤运行，输出分支覆盖率报表但不设硬性通过线（基线模式），避免阻塞合并。

### R4. 交付物

- R4.1 `docs/quality-baseline-2026-08.md`：全部基线数据 + 测量命令 + 工具链当前得分。
- R4.2 pyproject.toml 工具配置（ruff/mypy/coverage/radon/vulture/import-linter 的 `[tool.*]`）。
- R4.3 `.github/workflows/ci.yml`。
- R4.4 vulture 死代码候选清单（写入基线文档或独立文件）。

## Constraints

- 不改动 `lion_code/`、`tests/`、`benchmarks/` 下任何产品/测试代码。本任务唯一允许的代码改动是 pyproject.toml 与新增 CI 文档。
- 不引入依赖的运行时行为变化；工具均为 dev/CI 用途。
- `docs/tui-migration-audit.md` 处于 git 已删除未提交状态——不处理它，除非用户明确要求（不在本任务范围内）。
- 基线数值只记录，不修复。修复留给后续精简阶段。
- 中文作为文档语言；代码注释与既有风格一致。

## Acceptance Criteria

- [ ] AC1: 基线文档存在，R1.1–R1.7 七项指标全部有数值与测量命令。
- [ ] AC2: 六种工具全部配置进 pyproject.toml，安装命令可复现。
- [ ] AC3: `.github/workflows/ci.yml` 存在，含用户指定的 5 条命令。
- [ ] AC4: 本任务没有修改任何 `lion_code/`、`tests/`、`benchmarks/` 下的 .py 文件（用 git diff 验证）。
- [ ] AC5: 每个工具记录了当前得分/违规数，作为后续「不得恶化」阈值。
- [ ] AC6: 基线数据（复杂度、覆盖率、测试耗时、行数）可从文档命令重新测得，无外部服务依赖。
