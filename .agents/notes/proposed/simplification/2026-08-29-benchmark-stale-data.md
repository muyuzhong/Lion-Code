# Agent Note: 清理 benchmarks 陈旧数据（dataset 引用已删模块、results 提交产物、_GOLD_REVISIONS 死键、fixture 路径）

- Status: proposed
- 日期: 2026-08-29
- 范围: `benchmarks/context_management/dataset.json`、`benchmarks/context_management/results/*.json`、`benchmarks/agent_e2e/corpus.py`、`benchmarks/memory_lexical_recall/fixtures.v1.json`

## Problem

`benchmarks/` 下四类陈旧数据，是 `stale-corpus-entries`（PR 落地）同域的新残留：

1. **`dataset.json` 引用已删模块**（`benchmarks/context_management/dataset.json:62,69`）：`cold_cache_cleanup` 场景的 source_files/facts 引用 `lion_code/autonomy.py`（文件不存在）；offline 探针不受影响，但 online 回放该场景必然 FileNotFoundError。formal_dataset.json 已逐一核对全部存在。
2. **results/ 已提交陈旧产物**（`benchmarks/context_management/results/{latest,final-summary,hot-cache-clean,formal-latest}.json`，git 跟踪）：全仓无代码/文档/测试读取；`latest.json` 与 `final-summary.json` 字节完全相同（7709B，cmp 验证）；键（`offline_layer_probes`/`comparison_managed_vs_raw`）与现行 `benchmark.py` 输出 schema（`offline_probes`/`source_snapshots`/`pricing`/`comparison`）不符——旧版生成器残留；`agent_e2e/results` 已 gitignore，此处漏配。
3. **`_GOLD_REVISIONS` 死键**（`benchmarks/agent_e2e/corpus.py:395-399`）：`lion-cross-file-refactor-03/04/06/07` 四个键在 `_PUBLIC_TASKS` 中已无对应任务条目（01/02/05/08-14 存在），`_PRIVATE_EVIDENCE`（:429-435）只遍历 `_PUBLIC_TASKS`，映射永不命中。
4. **fixture 引用已删模块**（`benchmarks/memory_lexical_recall/fixtures.v1.json:83`）：paths 引用已删的 `lion_code/capabilities/memory/models.py`。

## Proposal

1. `dataset.json`：把 `cold_cache_cleanup` 场景的 source_files/facts 换为现存文件（如 `lion_code/hooks.py`/`frontmatter.py`），或按 stale-corpus 先例给 dataset 加存在性校验门禁。
2. `results/`：删除 4 个陈旧产物文件（或补 `.gitignore`；删除不影响后续运行重新生成）。
3. `corpus.py`：删除 `_GOLD_REVISIONS` 4 个死键。
4. `fixtures.v1.json`：修正或移除 `models.py` 路径引用。

## Why not keep it

四类都是「引用已删事实」的延迟故障与无读者产物：online 回放会失败、提交的产物与现行 schema 不符、映射键永不命中。按 stale-corpus 先例与「彻底删除」原则清理。

## Acceptance criteria

- `rg -n "lion_code/autonomy.py" benchmarks/` 零命中；对 dataset 内容做文件存在性校验（若加门禁）。
- `git status` 显示 results/ 不再被跟踪（若补 gitignore）或文件删除。
- `rg -n "cross-file-refactor-0[3476]\"" benchmarks/agent_e2e/corpus.py` 零命中；`tests/benchmarks/` 全绿。

## Risks

- 若 `results/` 某个文件被外部流程（非仓库内）读取，删除需确认；`formal-latest.json` 是 `formal_benchmark.py:65` 的写出目标——写出目标与提交的旧产物分离，删除不影响运行。