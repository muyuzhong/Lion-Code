# Lion 质量基线（2026-08-01）

> 代码精简第一阶段产出。本文件记录**当前代码库的真实质量基线**，所有数字可从文末命令重新测得。
> 原则：先记录基线 → 执行「不得继续恶化」→ 后续阶段按模块逐步提高标准。

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
| 2,397 | `lion_code/agent.py` |
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
| 553 | `lion_code/dream.py` |
| 552 | `lion_code/tui/state.py` |
| 546 | `lion_code/core/loop.py` |
| 528 | `tests/core/test_harness.py` |
| 520 | `lion_code/session_memory.py` |
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
| F (44) | `lion_code/__main__.py: run_repl` |
| F (44) | `lion_code/core/loop.py: run_agent_loop` |
| E (32) | `lion_code/agent.py: Agent.configure_api` |
| D (28) | `lion_code/application/session.py: LionCodingSession._drive` |
| D (26) | `lion_code/dream.py: parse_dream_plan` |
| D (22) | `lion_code/agent.py: Agent.__init__` |
| C (20) | `lion_code/dream.py: apply_dream_plan` |
| C (20) | `lion_code/hooks.py: _run_command_hook` |

## 5. 可维护性指数（radon mi，最差）

`agent.py` C、`hooks.py` C、`providers/openai_compatible.py` C、`tui/app.py` C、`tui/widgets.py` C

## 6. 循环依赖

- **ast Tarjan 粗测**：模块级 0 个循环。
- **import-linter 复核**：分析 145 文件 / 709 依赖，**3 条架构契约全部 KEPT**。
- 契约清单（`pyproject.toml [tool.importlinter]`）：
  1. TUI 不直接依赖 memory_runtime/session_runtime（间接经 application→agent 的路径为现状，允许）
  2. Application 不依赖 TUI
  3. 生产代码不导入 tests/benchmarks

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

> ⚠️ `agent.py` 同时是最大文件（2,397 行）、高复杂度（272）、最高提交频率（48），是后续精简的第一优先目标。

## 8. 分支覆盖率（coverage.py --branch）

- **lion_code：70%**（11,262 语句 / 3,572 分支，634 分支未覆盖）
- 全项目含 tests：76%

**最差模块**（≤50%）：

| 覆盖率 | 模块 |
|---|---|
| 24% | `lion_code/tui/terminal_title.py` |
| 40% | `lion_code/ui.py` |
| 46% | `lion_code/tui/widgets.py` |
| 53% | `lion_code/tui/terminal_notification.py` |

## 9. 测试与稳定性

- **全量：543 passed, 6 skipped, 6 subtests passed，耗时约 73s**（2026-08-01 本机 Python 3.13；三阶段-1 后:含 10 个 /goal//loop 特征测试）
- **不稳定候选**：`PytestUnhandledThreadExceptionWarning` —— `UnicodeEncodeError: 'gbk' codec can't encode character '⠴'`（测试/应用内线程在 GBK 环境打印 Unicode 字符导致）。建议后续在 `PYTHONIOENCODING=utf-8` 下复测确认。

## 10. 静态工具基线（配置后）

| 工具 | 当前状态 | 基线值 |
|---|---|---|
| `ruff check .` | 218 错，162 可自动修复 | 218 |
| `ruff format --check .` | 146 文件待重排 / 205 已合规 | 146 |
| `mypy lion_code` | 105 错 / 14 文件 | 105 |
| `vulture` (min-conf 70) | 5 个高置信候选 | 5 |
| `import-linter` | 3 契约 KEPT | 0 broken |
| `coverage` | lion_code 70% 分支 | 70% |

**ruff 违规分布**：I001 (import 排序) 78、F401 (未用 import) 34、UP037 (类型别名) 20、其余散落（UP024/UP017/UP009/RUF012 等）。**忽略项及原因见 `pyproject.toml [tool.ruff.lint]`**（含 RUF001/002/003 中文项目误报、E501 行宽、E402 条件导入等）。

**vulture 候选**：

| 位置 | 类型 |
|---|---|
| `lion_code/__main__.py:108` | unused variable `sig` |
| `lion_code/providers/thinking.py:104,113` | unused variable `provider_kind` |
| `tests/benchmarks/test_external_anchor.py:65` | unused variable `output_dir` |
| `tests/test_agent_run.py:67` | unsatisfiable `if` |

## 11. CI 门槛（不得继续恶化）

`.github/workflows/ci.yml` 的 fail 阈值（超出即 CI 失败）：

| 指标 | 基线 | 阈值含义 |
|---|---|---|
| ruff check 错误数 | 218 | 新增代码不得引入更多违规 |
| ruff format 待重排文件 | 146 | 新增文件必须格式合规 |
| mypy 错误数 | 105 | 新增代码不得引入更多类型错误 |
| import-linter | 0 broken | 不得打破架构边界 |
| pytest | 全部通过 | 不得回归 |
| 覆盖率 | 70% | 不设 fail_under（基线模式） |

> 阈值随代码演进人工更新：`git log` 变更被接受时，同步上调/下调基线文档与 CI 数值。

## 12. 复现命令

```bash
# 规模
find lion_code tests benchmarks -name "*.py" -not -path "*__pycache__*" -exec wc -l {} + | sort -rn

# 复杂度
radon cc lion_code -s -a
radon mi lion_code -n B

# 循环依赖
lint-imports --no-cache

# churn 热点
git log --name-only --pretty=format: | grep -v '^$' | sort | uniq -c | sort -rn

# 静态检查
ruff check .
ruff format --check .
python -m mypy lion_code
vulture lion_code tests --min-confidence 70

# 测试 + 覆盖率
python -m pytest -q
python -m coverage run --branch -m pytest -q
python -m coverage report --include="lion_code/*"

# 编译检查
python -m compileall -q lion_code tests
```

> 本文件数字均在 **2026-08-01**、Python 3.13.12、上述 `pyproject.toml` 配置下测得。
