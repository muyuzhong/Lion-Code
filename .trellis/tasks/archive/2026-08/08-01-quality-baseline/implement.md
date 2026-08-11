# 质量基线：实施计划

## 执行顺序

### Step 1 — 探测真实依赖图（import-linter 前提）
- 用脚本/import-linter 探测 `lion_code` 实际包间依赖。
- 产出：真实依赖矩阵，作为契约层定义依据。
- 验证：无失败条件，仅记录。

### Step 2 — 完整测量基线
| 指标 | 命令 | 已测得 | 状态 |
|---|---|---|---|
| 行数/文件数 | wc/find | 生产 107 文件 22,713 行；测试 86 文件 14,514；bench 18 文件 7,907 | ✅ |
| 最大 20 文件 | wc -l | 已得 top 5，需补全 20 | 部分 |
| 最大 20 函数 | ast | 已得 | ✅ |
| 复杂度（radon） | `radon cc lion_code -s -a` | 1169 A / 130 B / 53 C / 8 D / 2 E / 2 F；平均 3.31 (A) | ✅ |
| 可维护性指数 | `radon mi lion_code -n B` | agent.py C、hooks.py C、openai_compatible.py C、app.py C、widgets.py C | ✅ |
| 循环依赖 | ast Tarjan | 0 模块级循环 | ✅（import-linter 复核） |
| churn 热点 | git log + ast | agent.py cc272/48commit、app.py cc146/14、__main__.py cc87/15、loop.py cc80/9 | ✅ |
| 分支覆盖率 | coverage run --branch | 后台运行中 | ⏳ |
| 测试耗时 | pytest -q | 532 passed, 6 skipped, **80.31s**；1 个 PytestUnhandledThreadExceptionWarning（GBK UnicodeEncodeError） | ✅ |

### Step 3 — 写基线文档
- 创建 `docs/quality-baseline-2026-08.md`，按 R1.1–R1.7 组织，每项附命令。
- 记录 vulture 4 候选、ruff 423 错分布、mypy 103 错、format 147 文件。
- 标注不稳定测试候选（GBK 编码 warning）。

### Step 4 — 配置 pyproject.toml
- 新增 `[tool.ruff]`、`[tool.mypy]`、`[tool.pytest.ini_options]`、`[tool.coverage.*]`、`[tool.radon.cc]`、`[tool.vulture]`、`[tool.importlinter]`。
- `[project.optional-dependencies]` 加 `dev` 组：coverage、radon、vulture、import-linter、mypy、ruff、pytest、pytest-asyncio。
- 验证：`ruff check .` 在选定子集下全绿 or 记录残余；`python -m compileall -q lion_code tests` 通过。

### Step 5 — 写 lint_contracts.py + 跑 import-linter
- 按 Step 1 依赖图写契约文件。
- 验证：`lint-imports` 运行；若契约与现状不符，调整契约到反映现状，并记录不匹配项。

### Step 6 — 写 .github/workflows/ci.yml
- Job `lint`：ruff check、ruff format --check、compileall、git diff --check、import-linter（不阻塞）、mypy（报告）。
- Job `test`：pytest -q、coverage（报告）。
- **决策点 D1 待用户确认**：是否加「违规数 > 基线 → fail」比对步骤。

### Step 7 — 决策点 D1 确认
- 询问用户：CI 是否在本任务内加 fail 阈值。
- 若加：CI 增加基线比对步骤（当前违规数 vs 基线文档/文件）。
- 若不加：基线文档已记录数值，留作人工阈值。

### Step 8 — 验证 AC
- AC1–AC6 逐条核对。
- **AC4 关键验证**：`git diff --name-only` 确认没有改动 lion_code/tests/benchmarks 下任何 .py。

### Step 9 — 提交
- 按记忆约定：master 分支先开分支再提交；commit 不询问。

## 验证命令清单

```bash
# 复杂度
radon cc lion_code -s -a
radon mi lion_code -n B
# 死代码
vulture lion_code tests --min-confidence 70
# 格式/lint（基线模式）
ruff check . --output-format=concise | tail -3
ruff format --check . 2>&1 | tail -3
# 类型
python -m mypy lion_code --ignore-missing-imports | tail -3
# 测试+覆盖率
python -m pytest -q
coverage run --branch -m pytest -q && coverage report --branch
# 循环依赖
lint-imports
# 不改代码验证
git diff --name-only
```

## 回滚点

- Step 4 前：无代码改动，纯测量。
- Step 4 后：pyproject.toml 改动可 `git checkout` 撤销；CI/文档为新增文件，删除即可。
- 全程不触碰生产代码，无功能回归风险。

## 依赖与前提

- Python 3.12+ 可用（本机 3.13.12，CI 用 3.12）。
- 工具全部 pip 可装（coverage/radon/vulture 已装，import-linter 已有）。
