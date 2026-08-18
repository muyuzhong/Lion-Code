# Agent Note: 清理评测语料库中引用已删除模块与缺失测试的历史任务条目

- Status: proposed
- 日期: 2026-08-18
- 范围: `benchmarks/agent_e2e/corpus.py`、`benchmarks/agent_e2e/corpus_assets/public_catalog.v1.json`、`tests/benchmarks/test_corpus.py`

## Problem

PR9/PR7b 完整删除 Memory/Dream/Learning/MCP 与 legacy TUI 后，
`benchmarks/agent_e2e/corpus.py` 的 `_PUBLIC_TASKS` 里仍有任务条目引用已不存在的
模块与测试文件（workers 在**当前工作树**上跑 validation，不做历史 revision
checkout——`rg "gold_revision|checkout" benchmarks/agent_e2e/{orchestrator,worker,
agent_worker}.py` 零命中）：

- `lion-cross-file-refactor-03`（corpus.py:317）：involved_files 含
  `lion_code/dream.py`、`lion_code/session.py`（已删）。
- `lion-cross-file-refactor-04`（:318）：含 `lion_code/memory_runtime/coordinator.py`
  （已删）与 `tests/memory_runtime/test_core_integration.py`（文件不存在）。
- `lion-cross-file-refactor-06`（:320）：含 `lion_code/dream.py`、
  `lion_code/providers/oneshot.py`（已删）与 validation 命令
  `tests/providers/test_oneshot.py`（不存在）。
- 其余 validation 命令引用缺失测试：`tests/application/test_coding_session.py`
  （refactor-02、bugfix-10、feature-01）、`tests/test_legacy_tui.py`
  （refactor-07）——这些文件当前不存在。
- 同一批条目已随 SHA-256 锁定进 `corpus_assets/public_catalog.v1.json`
  （:83/:94/:188/:200 可见 `dream.py` 引用），`tests/benchmarks/test_corpus.py:39`
  的 `validate_bundled_corpus()` 只校验哈希与内部一致性，不校验文件存在性，
  所以这些失效条目能通过现有门禁。

## Proposal

1. 把引用已删除模块/缺失测试的任务条目从语料库**退役**（`TaskStatus.ARCHIVED`
   或直接移除）；保留任务卡的历史语义，但在 `benchmarks/agent_e2e/corpus.py`
   与 `public_catalog.v1.json` 同步删除/标记。
2. 按语料库协议处理：`CORPUS_VERSION` 升 v2（corpus.py:18）、重新计算
   `catalog_sha256`/条目哈希、同步 `tests/benchmarks/test_corpus.py` 的期望
   （若它对条目数/哈希有断言），跑 `validate_bundled_corpus()` 全绿。
3. 顺便核对 `agent-e2e-evaluation.md` 里「regression 对比自动跑基线」的
   任务选择逻辑，确保退役条目不进入基线对比。

## Why not keep it

「历史回放」任务描述的是历史上真实发生过的重构——但评测在**当前树**上执行
validation，涉及已删文件的任务根本无法跑通；它们占据 ACTIVE 状态只会让未来的
基线对比或任务选择误入无效集合。任务描述的历史事实可保留在 git 历史里，
语料库应只包含当前可验证的条目（这正是 `TaskStatus` 存在的意义）。

## Acceptance criteria

- `rg -n "lion_code/dream.py|lion_code/session.py|memory_runtime/coordinator.py|providers/oneshot.py|test_oneshot|test_legacy_tui|test_coding_session.py" benchmarks/agent_e2e` 零命中。
- `python -m pytest -q tests/benchmarks/test_corpus.py` 全绿；语料库哈希自洽。
- 全量可跑 unittest 通过；`git diff --check` 干净。

## Risks

- 语料库是钉定版本资产，改动需要整体升版并重算哈希——若版本协议要求不可变，
  则本提案退化为「新增 v2 常驻校验：ACTIVE 条目的 involved_files 与 validation
  命令必须存在」，由门禁阻止下一次失效条目进入，而非改写历史 v1。

## 落地

- 提交: `e472373ee23ec8c02a7094aef5043c9fd2ecb67e`（squash merge）
- PR: #59（标题：refactor: 为语料库 ACTIVE 条目增加文件存在性校验门禁（保留 v1 钉定资产不变））
- 门禁证据: 定向测试全绿（排除 5 个已知环境性/既有失败：test_coding_session_ports、test_composition_profiles::test_all_profiles_return_meta_facade、test_capability_migration::test_session_participant、test_agent_core_runtime::test_plan_clear、test_cli::test_repl_routes_generic_command）；CI Quality gates 已通过（2026-08-18）。
