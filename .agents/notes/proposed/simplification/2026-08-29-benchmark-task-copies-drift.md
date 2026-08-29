# Agent Note: 收口 benchmarks 测试中 TaskSpec/make_task 拷贝漂移（共享 fixture）

- Status: proposed
- 日期: 2026-08-29
- 范围: `tests/benchmarks/test_verified_contracts.py`、`test_verified_cli_composition.py`、`test_verified_execution_chain.py`、`test_eval_analysis_observability.py`、`test_orchestrator.py`、`test_models_catalog.py`

## Problem

`tests/benchmarks/` 中多处「verified-task-1」TaskSpec / make_task / manifest 的拷贝已经从同一事实漂移：

1. `public_prompt` 文案漂移：`test_verified_contracts.py:76`、`test_verified_cli_composition.py:72`、`test_verified_execution_chain.py:77` 均为 `"修复公开问题。"`，而 `test_eval_analysis_observability.py:208` 是 `"公开任务"`、`test_orchestrator.py:40` 是 `"修复问题。"`。
2. `make_task` 两处拷贝（cli_composition:80-110 vs execution_chain:85-117）的 `public_prompt` 与 `difficulty`（1 vs 2）字段不同；manifest 的 `agent_code_sha`/`evaluator_code_sha`（`"a"*7`/`"e"*7"` vs `"abcdef0"`/`"1234567"`）漂移，其余结构逐行相同。
3. extensions 键差异（d4：`swebench_instance_id` vs `harbor_task_name`）是语义性的，不应合并；但纯文案与 SHA 不应漂移。

## Proposal

1. 至少统一四处 `public_prompt` 文案与 make_task/manifest 的纯数据字段。
2. 较优做法：抽共享 fixture（`tests/benchmarks/fixtures/` 已有先例）承载 verified-task-1 的 TaskSpec/make_task/manifest 基线，各测试文件改引用；仅保留各自的语义性 extensions 差异。

## Why not keep it

「多个测试文件钉同一事实但互相漂移」正是测试冗余的典型代价：改一处不会自动改另一处，最终谁是真值不可判。共享 fixture 后单一事实源，文案/SHA 归属清晰。

## Acceptance criteria

- `rg -n '"修复公开问题。"|"公开任务"|"修复问题。"' tests/benchmarks/` 至多一处（fixture 内）。
- `tests/benchmarks/` 全绿。

## Risks

- 合并需参数化（各文件的 extensions 与断言字段不同），可能掩盖单测意图——建议只合并逐字节相同/纯数据部分，保留语义差异。