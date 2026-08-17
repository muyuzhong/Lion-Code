# Lion 质量基线（2026-08-01 建立；2026-08-04 CI 门禁收紧）

> 代码精简阶段产出。本文件记录质量基线的人类可读说明；CI 的权威机器基线为
> `docs/quality-baseline-2026-08.json`。
> 原则：先记录基线 → 执行「不得继续恶化」→ 后续阶段按模块逐步提高标准。
> PR9 于 2026-08-17 复测：旧项目 Memory、Dream、Learning 生产链路及其专属
> 测试与质量基线条目已删除；canonical JSONL Session entry 模型保留。
> 2026-08-04 复测：CI 门槛切到 Python 3.12.13 + Linux 平台 + 精确固定 dev 工具；
> Ruff/mypy 不再解析人类可读文本，而是用机器输出和违规指纹比对。

## 1. 规模

| 分区 | 文件数 | 行数 |
|---|---|---|
| 生产代码 `lion_code/` | 107 | 22,713 |
| 测试 `tests/` | 86 | 14,514 |
| Benchmark `benchmarks/` | 18 | 7,907 |
| **合计** | **211** | **45,134** |

## 2. 最大 20 个文件（按行数）

| 行数 | 文件 |
|---|---|
| 1,801 | `lion_code/agent.py` |
| 2,260 | `lion_code/tui/widgets.py` |
| 1,417 | `benchmarks/agent_e2e/external_anchor.py` |
| 1,399 | `lion_code/tui/app.py` |
| 1,252 | `benchmarks/context_management/benchmark.py` |
| 1,127 | `lion_code/providers/openai_compatible.py` |
| 1,069 | `benchmarks/context_management/formal_benchmark.py` |
| 1,000 | `tests/integration/test_agent_core_runtime.py` |
| 897 | `benchmarks/agent_e2e/regression.py` |
| 776 | `tests/test_hooks.py` |
| 721 | `lion_code/hooks.py` |
| 717 | `tests/application/test_coding_session.py` |
| 700 | `tests/tui/test_tui_app.py` |
| 556 | `tests/tui/test_tui_autocomplete.py` |
| 552 | `lion_code/tui/state.py` |
| 546 | `lion_code/core/loop.py` |
| 528 | `tests/core/test_harness.py` |
| 514 | `lion_code/application/session.py` |

## 3. 最大 20 个函数（按 body 行数）

| 行数 | 函数 |
|---|---|
| 92 | `lion_code/agent.py: Agent.__init__` |
| 29 | `lion_code/agent.py: Agent.configure_api` |
| 26 | `tests/integration/test_provider_core_tool_runtime.py: test_closed_loop_carries_tool_transcript_into_second_request` |
| 26 | `benchmarks/context_management/formal_benchmark.py: main` |
| 25 | `tests/integration/test_agent_core_runtime.py: test_legacy_json_is_migrated_without_deleting_source` |
| 25 | `tests/integration/test_agent_core_runtime.py: test_automatic_compaction_persists_summary_and_keeps_recent_turn` |
| 25 | `lion_code/agent.py: Agent._compact_core_context_if_needed` |
| 24 | `tests/test_hooks.py: test_project_hook_requires_and_persists_explicit_trust` |
| 24 | `tests/benchmarks/test_regression_feedback.py: test_gate_statuses_and_rejected_candidate_ledger` |
| 24 | `lion_code/agent.py: Agent.restore_core_session` |
| 23 | `tests/integration/test_agent_core_runtime.py: test_configure_api_replaces_provider_in_existing_runtime` |
| 23 | `lion_code/tui/widgets.py: _redraw` |
| 22 | `tests/providers/test_openai_compatible.py: test_text_parse_usage_and_request_shape` |
| 22 | `tests/integration/test_agent_core_runtime.py: test_plan_clear_and_execute_compacts_without_deleting_history` |
| 22 | `lion_code/tui/widgets.py: refresh_invocation` |
| 22 | `lion_code/hooks.py: _run_command_hook` |
| 21 | `lion_code/tui/widgets.py: update_thinking_visibility` |
| 21 | `tests/benchmarks/test_orchestrator.py: test_timeout_worker_exception_verifier_exception_and_cleanup_failure_are_invalid` |
| 21 | `lion_code/agent.py: Agent.clear_history` |
| 21 | `lion_code/tui/widgets.py: append_item` |

> 注：生产代码函数普遍不长（最大 92 行），模块过大而非单函数过大是主要问题。

## 4. 圈复杂度（radon）

**分级分布**（1364 blocks 分析）：

| 级别 | 数量 |
|---|---|
| A (1-5) | 1,169 |
| B (6-10) | 130 |
| C (11-20) | 53 |
| D (21-30) | 8 |
| E (31-40) | 2 |
| F (41+) | 2 |

**平均复杂度：A（3.31）**

**最差函数**：

| 复杂度 | 函数 |
|---|---|
| F (44) | `lion_code/core/loop.py: run_agent_loop` |
| E (32) | `lion_code/tui/app.py: LionTuiApp._apply_streaming_transcript_event` |
| E (31) | `lion_code/__main__.py: main` |
| D (29) | `lion_code/providers/stream.py: canonicalize_provider_stream` |
| D (28) | `lion_code/application/session.py: LionCodingSession._drive` |
| D (27) | `lion_code/__main__.py: run_repl` |

## 5. 可维护性指数（radon mi，最差）

`agent.py` C、`hooks.py` C、`providers/openai_compatible.py` C、`tui/app.py` C、`tui/widgets.py` C

## 6. 循环依赖

- **ast Tarjan 粗测**：模块级 0 个循环。
- **import-linter 复核**：分析 150 文件 / 750 依赖，**5 条架构契约全部 KEPT**。
- 契约清单（`pyproject.toml [tool.importlinter]`）：
  1. Core 不依赖 providers、tooling、application、tui。
  2. Providers 只依赖 Core 抽象。
  3. Application 不依赖 TUI。
  4. TUI 只经 Application/Core 接触运行时。
  5. 生产代码不导入 tests 与 benchmarks。

## 7. 复杂度 × 提交频率（churn 热点）

| 复杂度 | 提交数 | 文件 |
|---|---|---|
| 272 | 48 | `lion_code/agent.py` |
| 146 | 14 | `lion_code/tui/app.py` |
| 87 | 15 | `lion_code/__main__.py` |
| 80 | 9 | `lion_code/core/loop.py` |
| 96 | 6 | `lion_code/hooks.py` |
| 61 | 7 | `lion_code/tools.py` |
| 50 | 10 | `lion_code/application/session.py` |

> ⚠️ `agent.py` 仍是高复杂度和高提交频率热点；本轮已从 1,890 行降至 1,801 行，
> 后续继续按路线拆分职责。

## 8. 覆盖率（coverage.py --branch）

CI 权威口径为 Python 3.12.13、`coverage==7.15.2`、`source = ["lion_code"]`。

- coverage report 总覆盖率：**73%**（11,141 语句 / 2,518 未覆盖 / 3,154 分支 / 537 部分分支）。
- coverage JSON 真实分支覆盖率：**58.56%**（1,847 / 3,154）；CI 全局分支覆盖率下限仍为 58.33%。
- changed-lines 覆盖率：新增或修改的可执行 `lion_code/*.py` 行必须 **≥80%**；没有变更的可执行生产代码行时跳过。

**最差模块**（≤50%）：

| 覆盖率 | 模块 |
|---|---|
| 14% | `lion_code/core/session/tree.py` |
| 14% | `lion_code/tools.py` |
| 22% | `lion_code/providers/http.py` |
| 26% | `lion_code/tui/terminal_title.py` |
| 40% | `lion_code/ui.py` |
| 46% | `lion_code/tui/widgets.py` |

## 9. 测试与稳定性

- **本次全量：705 passed, 21 skipped, 10 subtests passed，耗时约 72s**（Windows 本地复测；CI 仍以 Linux Python 3.12.13 为权威）。
- **本机 Windows 警告候选**：`PytestUnhandledThreadExceptionWarning` —— `UnicodeEncodeError: 'gbk' codec can't encode character '⠴'`（测试/应用内线程在 GBK 环境打印 Unicode spinner 导致）。该警告未在 Linux/UTF-8 CI 日志中复现；如后续复现，应单独修复输出编码。

## 10. 静态工具基线（配置后）

| 工具 | 当前状态 | 基线值 |
|---|---|---|
| `ruff check lion_code tests scripts --output-format=json` | 48 个违规指纹 | 54 且不得出现新指纹 |
| `ruff format --check lion_code tests scripts` | 74 文件待重排 | 79 且不得出现新文件指纹 |
| `mypy lion_code --platform linux -O json` | 38 个错误指纹 | 68 且不得出现新指纹 |
| `radon cc lion_code -j` | 9 个 D/E/F 级复杂度块 | 12 且不得出现新 D/E/F 指纹 |
| `vulture lion_code tests --min-confidence 70` | 3 个高置信候选 | 5 且不得出现新指纹 |
| `import-linter --no-cache` | 6 契约 KEPT | 0 broken |
| `coverage json` | 分支覆盖率 58.56% | ≥58.33%，changed-lines ≥80% |

本次删除同步移除了旧 Memory/Dream/Learning 文件对应的质量指纹；当前机器指纹以
`docs/quality-baseline-2026-08.json` 为准。**忽略项及原因见
`pyproject.toml [tool.ruff.lint]`**（含 RUF001/002/003 中文项目误报、E501 行宽、
E402 条件导入等）。

> 本机 Windows 默认 `mypy lion_code` 当前仍为 99 个错误；CI 以 Linux 平台为权威，因此显式传入 `--platform linux` 并把基线收紧为 68。

**vulture 候选**：

| 位置 | 类型 |
|---|---|
| `lion_code/__main__.py:103` | unused variable `sig` |
| `tests/benchmarks/test_external_anchor.py:65` | unused variable `output_dir` |
| `tests/test_agent_run.py:74` | unsatisfiable `if` |

## 11. CI 门槛（不得继续恶化）

`.github/workflows/ci.yml` 的 fail 条件：

| 指标 | 基线 | 阈值含义 |
|---|---|---|
| ruff check | 54 个 JSON 指纹 | 状态码只允许 0/1；数量不得超过基线；不得出现新指纹 |
| ruff format | 79 个文件指纹 | 状态码只允许 0/1；数量不得超过基线；不得出现新文件指纹 |
| mypy | 68 个 Linux JSONL 指纹 | 状态码只允许 0/1；数量不得超过基线；不得出现新指纹 |
| radon | 12 个 D/E/F 指纹 | 不允许新增 D/E/F 级复杂度块 |
| vulture | 5 个高置信指纹 | 状态码只允许 0/3；不允许新增高置信候选 |
| import-linter | 0 broken | 不得打破架构边界 |
| pytest | 全部通过 | 不得回归 |
| compileall | 0 error | `lion_code tests scripts` 必须可编译 |
| git diff --check | 0 error | 不允许尾随空白等 diff 问题 |
| coverage branch | 58.33% | 全局分支覆盖率不得低于当前真实值 |
| changed-lines coverage | 80% | 新增或修改的可执行生产代码行覆盖率不得低于 80% |

> 违规基线保存在 `docs/quality-baseline-2026-08.json`。后续主分支质量改善后，应同步下调 JSON 和本文档，避免旧预算长期宽松。
> workflow 只能定义 check；是否真正阻止失败 CI 合并，需要在 GitHub 分支保护里把 `Quality gates (baseline) (3.12.13)` 设为 required check，并限制管理员绕过。

## 12. 运行时边界门禁更新（2026-08-04）

当前 pyproject.toml 已将 5 条运行时边界合同纳入 CI 阻塞门禁：

1. Core 不依赖 providers、tooling、application、tui。
2. Providers 只依赖 Core 抽象。
3. Application 不依赖 TUI。
4. TUI 只经 Application/Core 接触运行时。
5. 生产代码不导入 tests 与 benchmarks。

补充的 tests/architecture/test_runtime_boundaries.py 以 AST 检查 Provider 私有消息
历史、旧消息路径、全局 UI Sink、SessionRecorder 构造点和 JSONL writer 旁路；
PR9 的 tests/architecture/test_legacy_memory_removal.py 负责旧 Memory/Dream/Learning
模块、对象和 ProjectionLayer 符号的负向门禁。CI 已同时运行 pytest 与
lint-imports --no-cache，因此这两类检查均会阻止架构回归。

## 13. 复现命令

```bash
# 依赖：CI 权威环境为 Python 3.12.13 + Linux；dev 工具使用 pyproject 精确固定版本
python -m pip install --upgrade pip
python -m pip install ".[dev]"

# 规模
find lion_code tests benchmarks -name "*.py" -not -path "*__pycache__*" -exec wc -l {} + | sort -rn

# 复杂度
radon cc lion_code -s -a
python -m radon cc lion_code -j > radon-cc.json
python scripts/check_quality_baseline.py radon-complexity radon-cc.json
radon mi lion_code -n B

# 循环依赖
lint-imports --no-cache

# churn 热点
git log --name-only --pretty=format: | grep -v '^$' | sort | uniq -c | sort -rn

# 静态检查
python -m ruff check lion_code tests scripts --output-format=json > ruff.json
python scripts/check_quality_baseline.py ruff-check ruff.json --status 1
python -m ruff format --check lion_code tests scripts > ruff-format.txt 2>&1
python scripts/check_quality_baseline.py ruff-format ruff-format.txt --status 1
python -m mypy lion_code --platform linux -O json > mypy.jsonl 2>&1
python scripts/check_quality_baseline.py mypy mypy.jsonl --status 1
python -m vulture lion_code tests --min-confidence 70 > vulture.txt 2>&1
python scripts/check_quality_baseline.py vulture vulture.txt --status 3

# 测试 + 覆盖率
python -m pytest -q
python -m coverage run --branch -m pytest -q
python -m coverage json -o coverage.json
python scripts/check_quality_baseline.py coverage coverage.json
python -m coverage report --include="lion_code/*"

# 编译检查
python -m compileall -q lion_code tests scripts
```

> CI 门禁数字均在 **2026-08-04**、Python 3.12.13、Linux 平台语义、上述精确固定
> dev 工具版本下测得；`docs/quality-baseline-2026-08.json` 是 workflow 的权威输入。
